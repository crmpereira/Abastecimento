import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FlatList,
  Linking,
  Platform,
  RefreshControl,
  StyleSheet,
  View,
  useWindowDimensions,
} from "react-native";
import { Appbar, Button, Card, Chip, Menu, Text, useTheme } from "react-native-paper";
import * as Location from "expo-location";
import {
  CombustivelFiltro,
  AnpMunicipiosApi,
  fetchAnpMunicipios,
  fetchPostosResumoPorCombustivel,
  getApiBaseUrl,
  PostoApi,
} from "../api/backend";
import { haversineKm } from "../lib/distance";

type Coords = { lat: number; lon: number };

export type PostosScreenProps = {
  readonly onLogout: () => Promise<void>;
};

function formatKm(km: number): string {
  if (!Number.isFinite(km)) return "";
  if (km < 1) return `${Math.round(km * 1000)} m`;
  return `${km.toFixed(1)} km`;
}

function formatData(ts: string | null): string {
  if (!ts) return "sem data";
  const d = new Date(ts);
  if (!Number.isFinite(d.getTime())) return ts;
  return d.toLocaleDateString("pt-BR");
}

function formatDia(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  if (!Number.isFinite(d.getTime())) return iso;
  return d.toLocaleDateString("pt-BR");
}

function formatHora(ts: string | null): string {
  if (!ts) return "sem hora";
  const d = new Date(ts);
  if (!Number.isFinite(d.getTime())) return "—";
  return d.toLocaleTimeString("pt-BR");
}

function formatEnderecoDisplay(display: string | null | undefined): string {
  if (!display) return "Endereço não disponível";
  return display;
}

function formatEnderecoCompacto(display: string | null | undefined): string {
  if (!display) return "Endereço não disponível";
  return display.replace("Santa Catarina", "SC").replace(" | Brasil", "");
}

function formatNomePosto(id: string): string {
  const m = /^posto(\d+)$/i.exec(id.trim());
  if (!m) return id;
  return `Posto de Gasolina ${m[1]}`;
}

function formatPreco(valor: number | null | undefined): string {
  if (typeof valor !== "number" || !Number.isFinite(valor)) return "—";
  const s = valor.toFixed(2).replace(".", ",");
  return `R$ ${s}`;
}

function formatPrecoNumero(valor: number | null | undefined): string {
  if (typeof valor !== "number" || !Number.isFinite(valor)) return "—";
  return valor.toFixed(2).replace(".", ",");
}

function anpPrecoNumero(valor: number | null | undefined): string {
  if (typeof valor !== "number" || !Number.isFinite(valor)) return "—";
  return valor.toFixed(2).replace(".", ",");
}

function normKey(s: string): string {
  return (s || "")
    .trim()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ")
    .toUpperCase();
}

const COR_PRECO_ANP_MAIOR = "#DC2626";
const COR_PRECO_ANP_MENOR_IGUAL = "#2563EB";

function labelCombustivel(c: CombustivelFiltro): string {
  if (c === "etanol") return "Etanol";
  if (c === "diesel") return "Diesel";
  return "Gasolina";
}

function precoFiltro(p: PostoApi, c: CombustivelFiltro): number | null {
  const precos = p.precos;
  if (!precos) return null;
  if (c === "etanol") return precos.etanol ?? null;
  if (c === "diesel") return (precos.diesel_s10 ?? null) ?? (precos.diesel_s500 ?? null);
  return (precos.gasolina_comum ?? null) ?? (precos.gasolina_aditivada ?? null);
}

export function PostosScreen({ onLogout }: PostosScreenProps) {
  const { width } = useWindowDimensions();
  const theme = useTheme();
  const [postos, setPostos] = useState<PostoApi[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [anp, setAnp] = useState<AnpMunicipiosApi | null>(null);
  const [erroAnp, setErroAnp] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [coords, setCoords] = useState<Coords | null>(null);
  const [localAtual, setLocalAtual] = useState<string | null>(null);
  const [combustivel, setCombustivel] = useState<CombustivelFiltro>("gasolina");
  const [menuVisible, setMenuVisible] = useState(false);
  const [dataRef, setDataRef] = useState<string | null>(null);
  const [enderecoMenuId, setEnderecoMenuId] = useState<string | null>(null);

  const cols = width >= 1200 ? 3 : width >= 860 ? 2 : 1;
  const pagePadding = width >= 720 ? 20 : 12;
  const maxWidth = cols === 1 ? 820 : 1280;

  useMemo(() => getApiBaseUrl(), []);

  const carregar = useCallback(async (c: CombustivelFiltro) => {
    setErro(null);
    setErroAnp(null);
    const [postosResp, anpResp] = await Promise.allSettled([
      fetchPostosResumoPorCombustivel(c),
      fetchAnpMunicipios({ uf: "SC", municipio: "JOINVILLE" }),
    ]);

    if (postosResp.status === "rejected") {
      throw postosResp.reason;
    }

    setPostos(postosResp.value.postos);
    setDataRef(postosResp.value.data ?? null);

    if (anpResp.status === "fulfilled") {
      setAnp(anpResp.value);
    } else {
      setAnp(null);
      setErroAnp(anpResp.reason?.message || "Falha ao carregar ANP");
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await carregar(combustivel);
    } catch (e: any) {
      setErro(e?.message || "Falha ao carregar postos");
    } finally {
      setRefreshing(false);
    }
  }, [carregar, combustivel]);

  const selecionarCombustivel = useCallback(
    async (c: CombustivelFiltro) => {
      setMenuVisible(false);
      setCombustivel(c);
      setRefreshing(true);
      try {
        await carregar(c);
      } catch (e: any) {
        setErro(e?.message || "Falha ao carregar postos");
      } finally {
        setRefreshing(false);
      }
    },
    [carregar]
  );

  useEffect(() => {
    (async () => {
      try {
        await carregar("gasolina");
      } catch (e: any) {
        setErro(e?.message || "Falha ao carregar postos");
      } finally {
        setCarregando(false);
      }
    })();
  }, [carregar]);

  useEffect(() => {
    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== "granted") {
          setCoords(null);
          setLocalAtual(null);
          return;
        }
        const pos = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        setCoords({ lat, lon });
        try {
          const places = await Location.reverseGeocodeAsync({ latitude: lat, longitude: lon });
          const p = places?.[0] ?? null;
          const cidade = (p?.city || p?.subregion || "").trim();
          const regiao = (p?.region || "").trim().replace("Santa Catarina", "SC");
          const uf = (p as any)?.isoCountryCode ? String((p as any).isoCountryCode).trim() : "";
          const label = [cidade, regiao].filter(Boolean).join("/");
          setLocalAtual(label || uf || null);
        } catch {
          setLocalAtual(null);
        }
      } catch {
        setCoords(null);
        setLocalAtual(null);
      }
    })();
  }, []);

  const postosComDistancia = useMemo(() => {
    if (!coords) return postos.map((p) => ({ ...p, _distKm: null as number | null }));
    return postos.map((p) => {
      const lat = p.coordenadas?.lat ?? null;
      const lon = p.coordenadas?.lon ?? null;
      if (lat === null || lon === null) return { ...p, _distKm: null as number | null };
      return {
        ...p,
        _distKm: haversineKm(coords.lat, coords.lon, lat, lon),
      };
    });
  }, [coords, postos]);

  const postosOrdenados = useMemo(() => {
    const copy = [...postosComDistancia];
    copy.sort((a, b) => {
      const ga = precoFiltro(a, combustivel);
      const gb = precoFiltro(b, combustivel);
      const gaOk = typeof ga === "number" && Number.isFinite(ga);
      const gbOk = typeof gb === "number" && Number.isFinite(gb);
      if (gaOk && gbOk && ga !== gb) return ga - gb;
      if (gaOk && !gbOk) return -1;
      if (!gaOk && gbOk) return 1;

      const da = (a as any)._distKm;
      const db = (b as any)._distKm;
      if (da === null && db === null) return a.id.localeCompare(b.id);
      if (da === null) return 1;
      if (db === null) return -1;
      return da - db;
    });
    return copy;
  }, [postosComDistancia, combustivel]);

  const menorPreco = useMemo(() => {
    let melhor: number | null = null;
    for (const p of postosOrdenados) {
      const v = precoFiltro(p, combustivel);
      if (typeof v !== "number" || !Number.isFinite(v)) continue;
      if (melhor === null || v < melhor) melhor = v;
    }
    return melhor;
  }, [postosOrdenados, combustivel]);

  const anpProdutos = useMemo(() => {
    if (anp?.produtos && Array.isArray(anp.produtos)) return anp.produtos;
    return [];
  }, [anp]);

  const anpPeriodoLabel = useMemo(() => {
    const ini = anp?.periodo?.inicio ?? null;
    const fim = anp?.periodo?.fim ?? null;
    if (!ini || !fim) return "—";
    return `${formatDia(ini)} a ${formatDia(fim)}`;
  }, [anp]);

  const anpPrecoMaxPorProduto = useMemo(() => {
    const m = new Map<string, number>();
    for (const p of anpProdutos) {
      const nome = typeof p?.produto === "string" ? p.produto : null;
      const max = typeof p?.preco_max === "number" && Number.isFinite(p.preco_max) ? p.preco_max : null;
      if (!nome || max === null) continue;
      m.set(normKey(nome), max);
    }
    return m;
  }, [anpProdutos]);

  const precoAnpGasolinaComum = anpPrecoMaxPorProduto.get(normKey("GASOLINA COMUM")) ?? null;
  const precoAnpGasolinaAdit = anpPrecoMaxPorProduto.get(normKey("GASOLINA ADITIVADA")) ?? null;
  const precoAnpEtanol = anpPrecoMaxPorProduto.get(normKey("ETANOL HIDRATADO")) ?? null;
  const precoAnpDieselS10 = anpPrecoMaxPorProduto.get(normKey("OLEO DIESEL S10")) ?? null;
  const precoAnpDiesel = anpPrecoMaxPorProduto.get(normKey("OLEO DIESEL")) ?? null;

  function corPorComparacao(valor: number | null | undefined, anpMax: number | null): string | null {
    if (typeof valor !== "number" || !Number.isFinite(valor)) return null;
    if (typeof anpMax !== "number" || !Number.isFinite(anpMax)) return null;
    if (valor > anpMax) return COR_PRECO_ANP_MAIOR;
    return COR_PRECO_ANP_MENOR_IGUAL;
  }

  function abrirNoMapa(p: PostoApi) {
    const lat = p.coordenadas?.lat ?? null;
    const lon = p.coordenadas?.lon ?? null;
    if (lat === null || lon === null) return;
    const url = `https://www.google.com/maps/search/?api=1&query=${lat},${lon}`;
    Linking.openURL(url);
  }

  async function sair() {
    await onLogout();
  }

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.background }]}>
      <Appbar.Header style={[styles.appbar, { backgroundColor: theme.colors.surface }]}>
        <Appbar.Content
          title={localAtual ? `Abastece Aqui • ${localAtual}` : "Abastece Aqui"}
          titleStyle={styles.appbarTitle}
        />
        <Appbar.Action icon="refresh" onPress={refresh} />
        <Appbar.Action icon="logout" onPress={sair} />
      </Appbar.Header>

      <View style={[styles.content, { padding: pagePadding }]}>
        <View style={[styles.inner, { maxWidth }]}>
          {erro ? (
            <Card
              style={[
                styles.errorCard,
                { backgroundColor: theme.colors.surface, borderColor: theme.colors.outlineVariant },
              ]}
            >
              <Card.Content>
                <Text variant="titleSmall">Erro</Text>
                <Text variant="bodyMedium">{erro}</Text>
                <Button mode="contained" onPress={refresh} style={styles.retryButton}>
                  Tentar novamente
                </Button>
              </Card.Content>
            </Card>
          ) : null}

          <FlatList
            key={`cols-${cols}`}
            data={postosOrdenados}
            keyExtractor={(item) => item.id}
            numColumns={cols}
            columnWrapperStyle={cols > 1 ? styles.columnWrapper : undefined}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
            style={styles.list}
            contentContainerStyle={styles.listContent}
            ListHeaderComponent={
              <View style={styles.listHeader}>
                <View style={styles.pills}>
                  <Menu
                    visible={menuVisible}
                    onDismiss={() => setMenuVisible(false)}
                    anchor={
                      <Chip
                        style={[styles.pill, { backgroundColor: theme.colors.surfaceVariant }]}
                        textStyle={styles.pillText}
                        compact
                        onPress={() => setMenuVisible(true)}
                      >
                        Menor {labelCombustivel(combustivel)}
                        {menorPreco !== null ? `: ${formatPreco(menorPreco)}` : ""}
                      </Chip>
                    }
                  >
                    <Menu.Item
                      title="Gasolina"
                      onPress={() => selecionarCombustivel("gasolina")}
                    />
                    <Menu.Item
                      title="Etanol"
                      onPress={() => selecionarCombustivel("etanol")}
                    />
                    <Menu.Item
                      title="Diesel"
                      onPress={() => selecionarCombustivel("diesel")}
                    />
                  </Menu>
                  <Chip
                    style={[styles.pill, { backgroundColor: theme.colors.surfaceVariant }]}
                    textStyle={styles.pillText}
                    compact
                  >
                    {postosOrdenados.length} postos
                  </Chip>
                  <Chip
                    style={[styles.pill, { backgroundColor: theme.colors.surfaceVariant }]}
                    textStyle={styles.pillText}
                    compact
                  >
                    Data: {formatDia(dataRef)}
                  </Chip>
                </View>

                <Card
                  style={[
                    styles.anpCard,
                    { backgroundColor: theme.colors.surface, borderColor: theme.colors.outlineVariant },
                  ]}
                >
                  <Card.Content>
                    <View style={styles.anpHeader}>
                      <Text variant="titleSmall">ANP (municípios)</Text>
                      <Text variant="bodySmall" style={styles.anpMeta}>
                        {anp?.municipio ?? "JOINVILLE"}/{anp?.uf ?? "SC"} • Período: {anpPeriodoLabel}
                      </Text>
                    </View>

                    {erroAnp ? (
                      <Text variant="bodySmall">{erroAnp}</Text>
                    ) : (
                      <View style={styles.anpRows}>
                        {anpProdutos.map((r, idx) => {
                          const produto =
                            (typeof r?.produto === "string" && r.produto.trim() ? r.produto.trim() : null) ??
                            `Produto ${idx + 1}`;
                          const unidade =
                            typeof r?.unidade === "string" && r.unidade.trim() ? r.unidade.trim() : null;
                          const minimo = typeof r?.preco_min === "number" ? r.preco_min : null;
                          const maximo = typeof r?.preco_max === "number" ? r.preco_max : null;
                          const postosPesq = typeof r?.postos_pesquisados === "number" ? r.postos_pesquisados : null;

                          return (
                            <View key={`${produto}-${idx}`} style={styles.anpRow}>
                              <View style={styles.anpRowLeft}>
                                <Text variant="bodySmall" style={styles.anpProduto}>
                                  {produto}
                                </Text>
                                <Text variant="bodySmall" style={styles.anpSub}>
                                  {postosPesq !== null ? `${Math.round(postosPesq)} postos` : "—"}
                                  {unidade ? ` • ${unidade}` : ""}
                                </Text>
                              </View>
                              <View style={styles.anpRowRight}>
                                <View style={styles.anpPriceRow}>
                                  <Text variant="bodySmall" style={styles.anpPriceLabel}>
                                    Preço Min.
                                  </Text>
                                  <Text variant="bodySmall" style={styles.anpPriceValue}>
                                    {anpPrecoNumero(minimo)}
                                  </Text>
                                </View>
                                <View style={styles.anpPriceRow}>
                                  <Text variant="bodySmall" style={styles.anpPriceLabel}>
                                    Preço Máx.
                                  </Text>
                                  <Text variant="bodySmall" style={styles.anpPriceValue}>
                                    {anpPrecoNumero(maximo)}
                                  </Text>
                                </View>
                              </View>
                            </View>
                          );
                        })}
                      </View>
                    )}
                  </Card.Content>
                </Card>
              </View>
            }
            ListEmptyComponent={
              <View style={styles.empty}>
                {carregando ? (
                  <Text variant="bodyMedium">Carregando...</Text>
                ) : (
                  <Text variant="bodyMedium">Nenhum posto encontrado.</Text>
                )}
              </View>
            }
            renderItem={({ item }) => {
              const dist = (item as any)._distKm as number | null;
              const lat = item.coordenadas?.lat ?? null;
              const lon = item.coordenadas?.lon ?? null;
              const ts = item.coordenadas?.timestamp_foto ?? null;
              const p = item.precos;
              const endereco = item.endereco?.display ?? null;
              const title =
                dist !== null ? `${formatNomePosto(item.id)} ( ${formatKm(dist)} )` : formatNomePosto(item.id);
              return (
                <View style={styles.cardWrap}>
                  <Card
                    style={[
                      styles.card,
                      { backgroundColor: theme.colors.surface, borderColor: theme.colors.outlineVariant },
                    ]}
                  >
                    <Card.Title
                      title={title}
                      titleStyle={styles.cardTitle}
                      style={styles.cardTitleContainer}
                    />
                    <Card.Content style={styles.cardContent}>
                      <Text variant="bodySmall" style={styles.row}>
                        {formatEnderecoCompacto(endereco)}
                      </Text>

                      <View style={styles.board}>
                        <View style={styles.boardHeader}>
                          <Text style={styles.boardHeaderLeft}>PREÇOS</Text>
                          <Text style={styles.boardHeaderRight}>R$</Text>
                        </View>

                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>GASOLINA COMUM</Text>
                          {(() => {
                            const cor = corPorComparacao(p?.gasolina_comum ?? null, precoAnpGasolinaComum);
                            return (
                          <Text
                            style={[
                              styles.boardValue,
                              cor ? { color: cor } : null,
                            ]}
                          >
                            {formatPrecoNumero(p?.gasolina_comum ?? null)}
                          </Text>
                            );
                          })()}
                        </View>
                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>GASOLINA ADIT.</Text>
                          {(() => {
                            const cor = corPorComparacao(p?.gasolina_aditivada ?? null, precoAnpGasolinaAdit);
                            return (
                          <Text
                            style={[
                              styles.boardValue,
                              cor ? { color: cor } : null,
                            ]}
                          >
                            {formatPrecoNumero(p?.gasolina_aditivada ?? null)}
                          </Text>
                            );
                          })()}
                        </View>
                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>ETANOL</Text>
                          {(() => {
                            const cor = corPorComparacao(p?.etanol ?? null, precoAnpEtanol);
                            return (
                          <Text
                            style={[
                              styles.boardValue,
                              cor ? { color: cor } : null,
                            ]}
                          >
                            {formatPrecoNumero(p?.etanol ?? null)}
                          </Text>
                            );
                          })()}
                        </View>
                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>DIESEL S10</Text>
                          {(() => {
                            const cor = corPorComparacao(p?.diesel_s10 ?? null, precoAnpDieselS10);
                            return (
                          <Text
                            style={[
                              styles.boardValue,
                              cor ? { color: cor } : null,
                            ]}
                          >
                            {formatPrecoNumero(p?.diesel_s10 ?? null)}
                          </Text>
                            );
                          })()}
                        </View>
                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>DIESEL S500</Text>
                          {(() => {
                            const cor = corPorComparacao(p?.diesel_s500 ?? null, precoAnpDiesel);
                            return (
                          <Text
                            style={[
                              styles.boardValue,
                              cor ? { color: cor } : null,
                            ]}
                          >
                            {formatPrecoNumero(p?.diesel_s500 ?? null)}
                          </Text>
                            );
                          })()}
                        </View>
                      </View>
                    </Card.Content>
                    <Card.Actions style={styles.actions}>
                      <Button
                        mode="outlined"
                        onPress={() => abrirNoMapa(item)}
                        disabled={lat === null || lon === null}
                        contentStyle={styles.actionButtonContent}
                        labelStyle={styles.actionButtonLabel}
                      >
                        Abrir no mapa
                      </Button>
                    </Card.Actions>
                  </Card>
                </View>
              );
            }}
          />
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  appbar: { borderBottomWidth: 1, borderBottomColor: "rgba(0,0,0,0.06)" },
  appbarTitle: { fontWeight: "700" },
  content: { flex: 1 },
  inner: { width: "100%", alignSelf: "center", flex: 1, minHeight: 0 },
  list: { flex: 1, minHeight: 0 },
  listContent: { paddingBottom: 28 },
  listHeader: { paddingTop: 12, paddingBottom: 4 },
  pills: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  pill: { borderRadius: 999 },
  pillText: { fontSize: 12, opacity: 0.85 },
  anpCard: { marginTop: 10, borderRadius: 18, borderWidth: 1 },
  anpHeader: { marginBottom: 8 },
  anpMeta: { opacity: 0.8, marginTop: 2 },
  anpRows: { gap: 8 },
  anpRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 12,
    paddingVertical: 6,
    borderTopWidth: 1,
    borderTopColor: "rgba(2, 6, 23, 0.10)",
  },
  anpRowLeft: { flex: 1, minWidth: 0 },
  anpProduto: { fontWeight: "700" },
  anpSub: { opacity: 0.75, marginTop: 1 },
  anpRowRight: { alignItems: "flex-end" },
  anpPriceRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 1 },
  anpPriceLabel: { opacity: 0.75 },
  anpPriceValue: {
    fontWeight: "800",
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
  },
  empty: { paddingTop: 24, paddingBottom: 24, alignItems: "center" },
  columnWrapper: { gap: 10 },
  cardWrap: { flex: 1, minWidth: 220, paddingTop: 6 },
  card: {
    borderRadius: 14,
    overflow: "hidden",
    borderWidth: 1,
    shadowColor: "#000",
    shadowOpacity: 0.06,
    shadowRadius: 10,
    shadowOffset: { width: 0, height: 5 },
    elevation: 1,
  },
  cardTitleContainer: { paddingTop: 6, paddingBottom: 4, paddingHorizontal: 4 },
  cardTitle: { fontWeight: "700", fontSize: 14, lineHeight: 17 },
  cardContent: { paddingTop: 0, paddingBottom: 8 },
  row: { opacity: 0.8, marginBottom: 6, fontSize: 11, lineHeight: 14 },
  metaRow: { alignItems: "flex-end", marginBottom: 6 },
  metaChip: { borderRadius: 999 },
  metaChipText: { fontSize: 11, opacity: 0.85 },
  board: {
    marginTop: 4,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "rgba(2, 6, 23, 0.14)",
    overflow: "hidden",
    backgroundColor: "#0B1220",
  },
  boardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 9,
    paddingVertical: 6,
    backgroundColor: "rgba(255,255,255,0.06)",
    borderBottomWidth: 1,
    borderBottomColor: "rgba(255,255,255,0.08)",
  },
  boardHeaderLeft: {
    color: "rgba(255,255,255,0.9)",
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.8,
  },
  boardHeaderRight: {
    color: "rgba(255,255,255,0.75)",
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  boardRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingHorizontal: 9,
    paddingVertical: 6,
  },
  boardLabel: {
    color: "rgba(226, 232, 240, 0.9)",
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
  boardValue: {
    color: "#34D399",
    fontSize: 12,
    fontWeight: "800",
    letterSpacing: 0.3,
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
  },
  actions: { paddingHorizontal: 8, paddingBottom: 6, paddingTop: 0 },
  actionButtonContent: { height: 32 },
  actionButtonLabel: { fontSize: 12, fontWeight: "600" },
  errorCard: { marginTop: 12, borderRadius: 18, borderWidth: 1 },
  retryButton: { marginTop: 10, alignSelf: "flex-start" },
});

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
import { Appbar, Button, Card, Chip, Text, useTheme } from "react-native-paper";
import * as Location from "expo-location";
import { fetchPostos, getApiBaseUrl, PostoApi } from "../api/backend";
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

function formatHora(ts: string | null): string {
  if (!ts) return "sem hora";
  const d = new Date(ts);
  if (!Number.isFinite(d.getTime())) return "—";
  return d.toLocaleTimeString("pt-BR");
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

export function PostosScreen({ onLogout }: PostosScreenProps) {
  const { width } = useWindowDimensions();
  const theme = useTheme();
  const [postos, setPostos] = useState<PostoApi[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [coords, setCoords] = useState<Coords | null>(null);

  const cols = width >= 1200 ? 3 : width >= 860 ? 2 : 1;
  const pagePadding = width >= 720 ? 20 : 12;
  const maxWidth = cols === 1 ? 820 : 1280;

  useMemo(() => getApiBaseUrl(), []);

  const carregar = useCallback(async () => {
    setErro(null);
    const data = await fetchPostos();
    setPostos(data);
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await carregar();
    } catch (e: any) {
      setErro(e?.message || "Falha ao carregar postos");
    } finally {
      setRefreshing(false);
    }
  }, [carregar]);

  useEffect(() => {
    (async () => {
      try {
        await carregar();
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
          return;
        }
        const pos = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        setCoords({ lat: pos.coords.latitude, lon: pos.coords.longitude });
      } catch {
        setCoords(null);
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
      const ga = a.precos?.gasolina_comum ?? null;
      const gb = b.precos?.gasolina_comum ?? null;
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
  }, [postosComDistancia]);

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
        <Appbar.Content title="Abastece Aqui" titleStyle={styles.appbarTitle} />
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
                  <Chip
                    style={[styles.pill, { backgroundColor: theme.colors.surfaceVariant }]}
                    textStyle={styles.pillText}
                    compact
                  >
                    Menor gasolina
                  </Chip>
                  <Chip
                    style={[styles.pill, { backgroundColor: theme.colors.surfaceVariant }]}
                    textStyle={styles.pillText}
                    compact
                  >
                    {postosOrdenados.length} postos
                  </Chip>
                </View>
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
              return (
                <View style={styles.cardWrap}>
                  <Card
                    style={[
                      styles.card,
                      { backgroundColor: theme.colors.surface, borderColor: theme.colors.outlineVariant },
                    ]}
                  >
                    <Card.Title
                      title={formatNomePosto(item.id)}
                      titleStyle={styles.cardTitle}
                      style={styles.cardTitleContainer}
                      right={
                        dist !== null
                          ? () => (
                              <Chip
                                style={[styles.chip, { backgroundColor: theme.colors.surfaceVariant }]}
                                textStyle={styles.chipText}
                                compact
                              >
                                {formatKm(dist)}
                              </Chip>
                            )
                          : undefined
                      }
                    />
                    <Card.Content style={styles.cardContent}>
                      <Text variant="bodySmall" style={styles.row}>
                        Data: {formatData(ts)}
                      </Text>
                      <Text variant="bodySmall" style={styles.row}>
                        Hora: {formatHora(ts)}
                      </Text>

                      <View style={styles.board}>
                        <View style={styles.boardHeader}>
                          <Text style={styles.boardHeaderLeft}>PREÇOS</Text>
                          <Text style={styles.boardHeaderRight}>R$</Text>
                        </View>

                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>GASOLINA COMUM</Text>
                          <Text style={styles.boardValue}>
                            {formatPrecoNumero(p?.gasolina_comum ?? null)}
                          </Text>
                        </View>
                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>GASOLINA ADIT.</Text>
                          <Text style={styles.boardValue}>
                            {formatPrecoNumero(p?.gasolina_aditivada ?? null)}
                          </Text>
                        </View>
                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>ETANOL</Text>
                          <Text style={styles.boardValue}>{formatPrecoNumero(p?.etanol ?? null)}</Text>
                        </View>
                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>DIESEL S10</Text>
                          <Text style={styles.boardValue}>
                            {formatPrecoNumero(p?.diesel_s10 ?? null)}
                          </Text>
                        </View>
                        <View style={styles.boardRow}>
                          <Text style={styles.boardLabel}>DIESEL S500</Text>
                          <Text style={styles.boardValue}>
                            {formatPrecoNumero(p?.diesel_s500 ?? null)}
                          </Text>
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
  empty: { paddingTop: 24, paddingBottom: 24, alignItems: "center" },
  columnWrapper: { gap: 12 },
  cardWrap: { flex: 1, minWidth: 240, paddingTop: 8 },
  card: {
    borderRadius: 16,
    overflow: "hidden",
    borderWidth: 1,
    shadowColor: "#000",
    shadowOpacity: 0.06,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 1,
  },
  cardTitleContainer: { paddingTop: 8, paddingBottom: 6, paddingHorizontal: 4 },
  cardTitle: { fontWeight: "700", fontSize: 15, lineHeight: 18 },
  chip: { marginRight: 10, borderRadius: 999 },
  chipText: { fontSize: 11, opacity: 0.85 },
  cardContent: { paddingTop: 4, paddingBottom: 8 },
  row: { opacity: 0.8, marginBottom: 3, fontSize: 11, lineHeight: 14 },
  board: {
    marginTop: 6,
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

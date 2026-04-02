import { useCallback, useEffect, useMemo, useState } from "react";
import {
  FlatList,
  Linking,
  RefreshControl,
  StyleSheet,
  View,
  useWindowDimensions,
} from "react-native";
import { Appbar, Button, Card, Chip, Text } from "react-native-paper";
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

export function PostosScreen({ onLogout }: PostosScreenProps) {
  const { width } = useWindowDimensions();
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
    <View style={styles.container}>
      <Appbar.Header>
        <Appbar.Content title="Postos" />
        <Appbar.Action icon="refresh" onPress={refresh} />
        <Appbar.Action icon="logout" onPress={sair} />
      </Appbar.Header>

      <View style={[styles.content, { padding: pagePadding }]}>
        <View style={[styles.inner, { maxWidth }]}>
          {erro ? (
            <Card style={styles.errorCard}>
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
                  <Card style={styles.card}>
                    <Card.Title
                      title={formatNomePosto(item.id)}
                      right={
                        dist !== null ? () => <Chip style={styles.chip}>{formatKm(dist)}</Chip> : undefined
                      }
                    />
                    <Card.Content>
                      <Text variant="bodySmall" style={styles.row}>
                        Data: {formatData(ts)}
                      </Text>
                      <Text variant="bodySmall" style={styles.row}>
                        Hora: {formatHora(ts)}
                      </Text>

                      <View style={styles.priceGrid}>
                        <Text variant="bodySmall" style={styles.priceItem}>
                          Gas. comum: {p?.gasolina_comum ?? "—"}
                        </Text>
                        <Text variant="bodySmall" style={styles.priceItem}>
                          Gas. adit.: {p?.gasolina_aditivada ?? "—"}
                        </Text>
                        <Text variant="bodySmall" style={styles.priceItem}>
                          Etanol: {p?.etanol ?? "—"}
                        </Text>
                        <Text variant="bodySmall" style={styles.priceItem}>
                          Diesel S10: {p?.diesel_s10 ?? "—"}
                        </Text>
                        <Text variant="bodySmall" style={styles.priceItem}>
                          Diesel S500: {p?.diesel_s500 ?? "—"}
                        </Text>
                      </View>
                    </Card.Content>
                    <Card.Actions style={styles.actions}>
                      <Button
                        mode="outlined"
                        onPress={() => abrirNoMapa(item)}
                        disabled={lat === null || lon === null}
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
  container: { flex: 1, backgroundColor: "#F5F7FB" },
  content: { flex: 1 },
  inner: { width: "100%", alignSelf: "center", flex: 1, minHeight: 0 },
  list: { flex: 1, minHeight: 0 },
  listContent: { paddingBottom: 24 },
  empty: { paddingTop: 24, paddingBottom: 24, alignItems: "center" },
  columnWrapper: { gap: 12 },
  cardWrap: { flex: 1, minWidth: 280, paddingTop: 12 },
  card: { borderRadius: 18, overflow: "hidden" },
  chip: { marginRight: 12 },
  row: { opacity: 0.85, marginBottom: 6 },
  priceGrid: { marginTop: 10, flexDirection: "row", flexWrap: "wrap", gap: 8 },
  priceItem: { minWidth: 170, flexGrow: 1 },
  actions: { paddingHorizontal: 8, paddingBottom: 8 },
  errorCard: { marginTop: 12, borderRadius: 18 },
  retryButton: { marginTop: 10, alignSelf: "flex-start" },
});

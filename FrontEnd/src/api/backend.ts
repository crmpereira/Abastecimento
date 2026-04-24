import { NativeModules, Platform } from "react-native";

export type PostoApi = {
  id: string;
  arquivo: string;
  coordenadas?: {
    lat: number | null;
    lon: number | null;
    timestamp_foto: string | null;
  };
  endereco?: {
    display?: string | null;
    rua?: string | null;
    numero?: string | null;
    bairro?: string | null;
    cidade?: string | null;
    uf?: string | null;
    cep?: string | null;
    pais?: string | null;
    provider?: string | null;
  } | null;
  precos?: {
    gasolina_aditivada: number | null;
    gasolina_comum: number | null;
    etanol: number | null;
    diesel_s10: number | null;
    diesel_s500: number | null;
  };
};

export type CombustivelFiltro = "gasolina" | "etanol" | "diesel";

export type PostosResumoApi = {
  data: string | null;
  total: number;
  combustivel: CombustivelFiltro | null;
  postos: PostoApi[];
};

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

function normalizeBaseUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

function guessApiBaseUrl(): string | null {
  if (Platform.OS === "web") {
    const hostname =
      typeof window !== "undefined" && window.location?.hostname ? window.location.hostname : null;
    if (hostname && hostname !== "localhost" && hostname !== "127.0.0.1") {
      return `http://${hostname}:8000`;
    }
    return null;
  }

  const scriptUrl = (NativeModules as any)?.SourceCode?.scriptURL as string | undefined;
  if (!scriptUrl || typeof scriptUrl !== "string") return null;
  const m = /^https?:\/\/([^:/?#]+)(?::\d+)?\//i.exec(scriptUrl);
  const host = m?.[1] ?? null;
  if (!host) return null;
  if (host === "localhost" || host === "127.0.0.1") return null;
  return `http://${host}:8000`;
}

export function getApiBaseUrl(): string {
  const envUrl = process.env.EXPO_PUBLIC_API_BASE_URL;
  if (envUrl && typeof envUrl === "string" && envUrl.trim()) {
    return normalizeBaseUrl(envUrl);
  }
  const guessed = guessApiBaseUrl();
  if (guessed) return normalizeBaseUrl(guessed);
  return DEFAULT_API_BASE_URL;
}

function getApiKey(): string | null {
  const key = process.env.EXPO_PUBLIC_API_KEY;
  if (key && typeof key === "string" && key.trim()) return key.trim();
  return null;
}

function buildHeaders(): HeadersInit {
  const apiKey = getApiKey();
  const headers: Record<string, string> = {};
  if (apiKey) headers["x-api-key"] = apiKey;
  return headers;
}

export async function fetchPostos(): Promise<PostoApi[]> {
  const baseUrl = getApiBaseUrl();
  const res = await fetch(`${baseUrl}/api/postos`, { headers: buildHeaders() });
  if (!res.ok) {
    throw new Error(`Falha ao buscar postos: HTTP ${res.status}`);
  }
  const data = (await res.json()) as unknown;
  if (!Array.isArray(data)) {
    return [];
  }
  return data as PostoApi[];
}

export async function fetchPostosPorCombustivel(combustivel: CombustivelFiltro): Promise<PostoApi[]> {
  const baseUrl = getApiBaseUrl();
  const qs = new URLSearchParams({ combustivel });
  const res = await fetch(`${baseUrl}/api/postos?${qs.toString()}`, { headers: buildHeaders() });
  if (!res.ok) {
    throw new Error(`Falha ao buscar postos: HTTP ${res.status}`);
  }
  const data = (await res.json()) as unknown;
  if (!Array.isArray(data)) {
    return [];
  }
  return data as PostoApi[];
}

export async function fetchPostosResumoPorCombustivel(
  combustivel: CombustivelFiltro
): Promise<PostosResumoApi> {
  const baseUrl = getApiBaseUrl();
  const qs = new URLSearchParams({ combustivel });
  const res = await fetch(`${baseUrl}/api/postos_resumo?${qs.toString()}`, { headers: buildHeaders() });
  if (!res.ok) {
    throw new Error(`Falha ao buscar postos: HTTP ${res.status}`);
  }
  const data = (await res.json()) as unknown;
  if (!data || typeof data !== "object") {
    return { data: null, total: 0, combustivel: null, postos: [] };
  }
  return data as PostosResumoApi;
}

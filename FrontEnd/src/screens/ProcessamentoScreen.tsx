import { useCallback, useEffect, useMemo, useState } from "react";
import { Platform, ScrollView, StyleSheet, View, useWindowDimensions } from "react-native";
import { Appbar, Button, Card, Checkbox, Divider, Text, useTheme } from "react-native-paper";
import {
  ProcessamentoJobApi,
  fetchProcessamentoJob,
  iniciarProcessamentoAnp,
  iniciarProcessamentoFotos,
  uploadFotos,
} from "../api/backend";

type Picked = {
  nome: string;
  tamanho: number;
  file: any;
};

export type ProcessamentoScreenProps = {
  readonly onBack: () => void;
  readonly onLogout: () => Promise<void>;
};

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const unidades = ["B", "KB", "MB", "GB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < unidades.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${unidades[i]}`;
}

async function selecionarArquivosEmPastaWindows(): Promise<Picked[]> {
  if (Platform.OS !== "web") return [];

  const w = globalThis as any;

  if (typeof w?.showDirectoryPicker === "function") {
    const dir = await w.showDirectoryPicker();
    const arquivos: Picked[] = [];
    for await (const [nome, handle] of dir.entries()) {
      if (!handle || handle.kind !== "file") continue;
      const ext = String(nome).toLowerCase();
      if (!ext.endsWith(".jpg") && !ext.endsWith(".jpeg") && !ext.endsWith(".png")) continue;
      const file = await handle.getFile();
      arquivos.push({ nome: file.name, tamanho: file.size, file });
    }
    arquivos.sort((a, b) => a.nome.localeCompare(b.nome));
    return arquivos;
  }

  if (typeof w?.document?.createElement === "function") {
    return await new Promise<Picked[]>((resolve) => {
      const input = w.document.createElement("input");
      input.type = "file";
      input.multiple = true;
      input.accept = ".jpg,.jpeg,.png,image/jpeg,image/png";
      input.webkitdirectory = true;
      input.onchange = () => {
        const files = Array.from(input.files || []);
        const out = files
          .filter((f: any) => f && typeof f.name === "string")
          .map((f: any) => ({ nome: f.name, tamanho: Number(f.size || 0), file: f }))
          .sort((a: Picked, b: Picked) => a.nome.localeCompare(b.nome));
        resolve(out);
      };
      input.click();
    });
  }

  return [];
}

function jobResumo(job: ProcessamentoJobApi | null): string {
  if (!job) return "";
  const status = job.status || "";
  if (status === "running") return "Em execução...";
  if (status === "done") return "Concluído";
  if (status === "error") return "Erro";
  return status;
}

export function ProcessamentoScreen({ onBack, onLogout }: ProcessamentoScreenProps) {
  const theme = useTheme();
  const { width } = useWindowDimensions();
  const pagePadding = width >= 720 ? 20 : 12;
  const maxWidth = 920;

  const [arquivos, setArquivos] = useState<Picked[]>([]);
  const [selecionados, setSelecionados] = useState<Record<string, boolean>>({});
  const [loadingFotos, setLoadingFotos] = useState(false);
  const [erroFotos, setErroFotos] = useState<string | null>(null);
  const [jobFotosId, setJobFotosId] = useState<string | null>(null);
  const [jobFotos, setJobFotos] = useState<ProcessamentoJobApi | null>(null);

  const [loadingAnp, setLoadingAnp] = useState(false);
  const [erroAnp, setErroAnp] = useState<string | null>(null);
  const [jobAnpId, setJobAnpId] = useState<string | null>(null);
  const [jobAnp, setJobAnp] = useState<ProcessamentoJobApi | null>(null);

  const selecionadosLista = useMemo(() => {
    const out: Picked[] = [];
    for (const a of arquivos) {
      if (selecionados[a.nome]) out.push(a);
    }
    return out;
  }, [arquivos, selecionados]);

  const todosMarcados = useMemo(() => {
    if (arquivos.length === 0) return false;
    return arquivos.every((a) => Boolean(selecionados[a.nome]));
  }, [arquivos, selecionados]);

  const marcarTodos = useCallback(() => {
    const next: Record<string, boolean> = {};
    for (const a of arquivos) next[a.nome] = !todosMarcados;
    setSelecionados(next);
  }, [arquivos, todosMarcados]);

  const toggle = useCallback((nome: string) => {
    setSelecionados((prev) => ({ ...prev, [nome]: !prev[nome] }));
  }, []);

  const escolherPasta = useCallback(async () => {
    setErroFotos(null);
    try {
      const picked = await selecionarArquivosEmPastaWindows();
      setArquivos(picked);
      const next: Record<string, boolean> = {};
      for (const a of picked) next[a.nome] = true;
      setSelecionados(next);
    } catch (e: any) {
      setErroFotos(e?.message || "Falha ao selecionar arquivos");
    }
  }, []);

  const iniciarFotos = useCallback(async () => {
    if (loadingFotos) return;
    setErroFotos(null);
    setLoadingFotos(true);
    try {
      if (Platform.OS !== "web") {
        throw new Error("Upload/seleção de pasta disponível apenas no Web (Windows)");
      }
      if (selecionadosLista.length === 0) {
        throw new Error("Selecione pelo menos um arquivo");
      }
      const uploadResp = await uploadFotos(selecionadosLista.map((a) => ({ nome: a.nome, file: a.file })));
      const job = await iniciarProcessamentoFotos(uploadResp.arquivos);
      setJobFotosId(job.job_id);
      setJobFotos(null);
    } catch (e: any) {
      setErroFotos(e?.message || "Falha ao iniciar processamento de fotos");
    } finally {
      setLoadingFotos(false);
    }
  }, [loadingFotos, selecionadosLista]);

  const iniciarAnp = useCallback(async () => {
    if (loadingAnp) return;
    setErroAnp(null);
    setLoadingAnp(true);
    try {
      const job = await iniciarProcessamentoAnp();
      setJobAnpId(job.job_id);
      setJobAnp(null);
    } catch (e: any) {
      setErroAnp(e?.message || "Falha ao iniciar processamento ANP");
    } finally {
      setLoadingAnp(false);
    }
  }, [loadingAnp]);

  useEffect(() => {
    if (!jobFotosId) return;
    let cancel = false;
    const tick = async () => {
      try {
        const j = await fetchProcessamentoJob(jobFotosId);
        if (!cancel) setJobFotos(j);
      } catch {
        if (!cancel) setJobFotos(null);
      }
    };
    tick();
    const id = setInterval(tick, 1500);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [jobFotosId]);

  useEffect(() => {
    if (!jobAnpId) return;
    let cancel = false;
    const tick = async () => {
      try {
        const j = await fetchProcessamentoJob(jobAnpId);
        if (!cancel) setJobAnp(j);
      } catch {
        if (!cancel) setJobAnp(null);
      }
    };
    tick();
    const id = setInterval(tick, 1500);
    return () => {
      cancel = true;
      clearInterval(id);
    };
  }, [jobAnpId]);

  const sair = useCallback(async () => {
    await onLogout();
  }, [onLogout]);

  return (
    <View style={[styles.container, { backgroundColor: theme.colors.background }]}>
      <Appbar.Header style={[styles.appbar, { backgroundColor: theme.colors.surface }]}>
        <Appbar.BackAction onPress={onBack} />
        <Appbar.Content title="Processamentos" titleStyle={styles.appbarTitle} />
        <Appbar.Action icon="logout" onPress={sair} />
      </Appbar.Header>

      <ScrollView contentContainerStyle={[styles.scroll, { padding: pagePadding }]}>
        <View style={[styles.inner, { maxWidth }]}>
          <Card style={[styles.card, { backgroundColor: theme.colors.surface, borderColor: theme.colors.outlineVariant }]}>
            <Card.Content>
              <Text variant="titleMedium">Fotos</Text>
              <Text variant="bodySmall" style={styles.muted}>
                Selecione uma pasta do Windows, marque os arquivos e execute o processamento.
              </Text>

              <View style={styles.row}>
                <Button mode="outlined" onPress={escolherPasta} disabled={Platform.OS !== "web"}>
                  Selecionar pasta
                </Button>
                <Button mode="outlined" onPress={marcarTodos} disabled={arquivos.length === 0}>
                  {todosMarcados ? "Desmarcar todos" : "Marcar todos"}
                </Button>
                <Button mode="contained" onPress={iniciarFotos} loading={loadingFotos}>
                  Subir e processar
                </Button>
              </View>

              {Platform.OS !== "web" ? (
                <Text variant="bodySmall" style={[styles.muted, { marginTop: 8 }]}>
                  Esta tela foi pensada para Web (Windows). No mobile, a seleção de pasta não está disponível.
                </Text>
              ) : null}

              {erroFotos ? (
                <Text variant="bodySmall" style={[styles.error, { color: theme.colors.error }]}>
                  {erroFotos}
                </Text>
              ) : null}

              <View style={styles.list}>
                {arquivos.length === 0 ? (
                  <Text variant="bodySmall" style={styles.muted}>
                    Nenhum arquivo selecionado.
                  </Text>
                ) : (
                  arquivos.map((a) => (
                    <View key={a.nome} style={styles.fileRow}>
                      <Checkbox status={selecionados[a.nome] ? "checked" : "unchecked"} onPress={() => toggle(a.nome)} />
                      <View style={styles.fileMeta}>
                        <Text numberOfLines={1} style={styles.fileName}>
                          {a.nome}
                        </Text>
                        <Text variant="bodySmall" style={styles.muted}>
                          {formatBytes(a.tamanho)}
                        </Text>
                      </View>
                    </View>
                  ))
                )}
              </View>

              {jobFotosId ? (
                <>
                  <Divider style={styles.divider} />
                  <Text variant="titleSmall">Status: {jobResumo(jobFotos)}</Text>
                  <Text variant="bodySmall" style={styles.muted}>
                    Job: {jobFotosId}
                  </Text>
                  {jobFotos?.saida ? (
                    <Text variant="bodySmall" style={styles.mono}>
                      {jobFotos.saida}
                    </Text>
                  ) : null}
                </>
              ) : null}
            </Card.Content>
          </Card>

          <Card style={[styles.card, { backgroundColor: theme.colors.surface, borderColor: theme.colors.outlineVariant }]}>
            <Card.Content>
              <Text variant="titleMedium">ANP</Text>
              <Text variant="bodySmall" style={styles.muted}>
                Executa o processamento para gerar (ou atualizar) o JSON da ANP.
              </Text>

              <View style={styles.row}>
                <Button mode="contained" onPress={iniciarAnp} loading={loadingAnp}>
                  Processar ANP
                </Button>
              </View>

              {erroAnp ? (
                <Text variant="bodySmall" style={[styles.error, { color: theme.colors.error }]}>
                  {erroAnp}
                </Text>
              ) : null}

              {jobAnpId ? (
                <>
                  <Divider style={styles.divider} />
                  <Text variant="titleSmall">Status: {jobResumo(jobAnp)}</Text>
                  <Text variant="bodySmall" style={styles.muted}>
                    Job: {jobAnpId}
                  </Text>
                  {jobAnp?.saida ? (
                    <Text variant="bodySmall" style={styles.mono}>
                      {jobAnp.saida}
                    </Text>
                  ) : null}
                </>
              ) : null}
            </Card.Content>
          </Card>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  appbar: { borderBottomWidth: 1, borderBottomColor: "rgba(0,0,0,0.06)" },
  appbarTitle: { fontWeight: "700" },
  scroll: { paddingBottom: 24 },
  inner: { width: "100%", alignSelf: "center", gap: 12 },
  card: { borderRadius: 18, borderWidth: 1, overflow: "hidden" },
  muted: { opacity: 0.75, marginTop: 4 },
  row: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 12 },
  error: { marginTop: 10 },
  list: { marginTop: 10 },
  fileRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4 },
  fileMeta: { flex: 1, minWidth: 0 },
  fileName: { fontWeight: "600" },
  divider: { marginVertical: 10 },
  mono: {
    marginTop: 8,
    fontFamily: Platform.select({ ios: "Menlo", android: "monospace", default: "monospace" }),
    fontSize: 12,
    lineHeight: 16,
    opacity: 0.9,
  },
});


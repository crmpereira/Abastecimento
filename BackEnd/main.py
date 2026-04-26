from fastapi import Body, FastAPI, File, HTTPException, Security, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
import os
import json
import datetime
import re
import subprocess
import sys
import threading
import time
import uuid

app = FastAPI(
    title="AbasteceAqui API",
    version="1.0.0",
    description="API para consultar os dados processados (JSON diário) e lista de postos.",
)

api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _processamento_dir():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    raiz = os.path.dirname(base_dir)
    return os.path.join(raiz, "Processamento")

def _fotos_dir():
    return os.path.join(_processamento_dir(), "Fotos")

def _api_key_configurada():
    return (os.getenv("ABASTECEAQUI_API_KEY") or "").strip()

def _checar_api_key(x_api_key: str | None):
    api_key = _api_key_configurada()
    if not api_key:
        return
    if not x_api_key or x_api_key.strip() != api_key:
        raise HTTPException(status_code=401, detail="Não autorizado")

def _datas_disponiveis():
    pasta = _processamento_dir()
    if not os.path.exists(pasta):
        return []
    datas = set()
    for nome in os.listdir(pasta):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:_\d{6})?\.json", nome)
        if m:
            datas.add(m.group(1))
    return sorted(datas)

def _arquivo_mais_recente(data_str: str | None = None):
    pasta = _processamento_dir()
    if not os.path.exists(pasta):
        return None

    candidatos: list[tuple[str, str, str]] = []
    for nome in os.listdir(pasta):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:_(\d{6}))?\.json", nome)
        if not m:
            continue
        dia = m.group(1)
        hora = m.group(2) or "000000"
        if data_str and dia != data_str:
            continue
        candidatos.append((dia, hora, os.path.join(pasta, nome)))

    if not candidatos:
        return None

    candidatos.sort()
    return candidatos[-1][2]


def _arquivo_do_dia(data_str=None):
    if not data_str:
        data_str = datetime.date.today().isoformat()
    return os.path.join(_processamento_dir(), f"{data_str}.json")

_CACHE_ARQUIVO_TS_FOTO: dict[str, object] = {}

def _parse_timestamp_foto(valor) -> datetime.datetime | None:
    if not valor or not isinstance(valor, str):
        return None
    s = valor.strip()
    if not s:
        return None
    s = s.replace(" ", "T")
    try:
        dt = datetime.datetime.fromisoformat(s)
    except Exception:
        try:
            dt = datetime.datetime.strptime(valor.strip(), "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return dt

def _max_timestamp_foto_do_json(dados: object) -> datetime.datetime | None:
    if not isinstance(dados, dict):
        return None
    postos = dados.get("postos")
    if not isinstance(postos, list):
        return None
    melhor: datetime.datetime | None = None
    for p in postos:
        if not isinstance(p, dict):
            continue
        coords = p.get("coordenadas")
        if not isinstance(coords, dict):
            continue
        dt = _parse_timestamp_foto(coords.get("timestamp_foto"))
        if dt is None:
            continue
        if melhor is None or dt > melhor:
            melhor = dt
    return melhor

def _arquivo_mais_recente_por_timestamp_foto():
    pasta = _processamento_dir()
    if not os.path.exists(pasta):
        return None

    nomes = []
    for nome in os.listdir(pasta):
        if re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:_(\d{6}))?\.json", nome):
            nomes.append(nome)
    if not nomes:
        return None

    assinatura = tuple(sorted((n, os.path.getmtime(os.path.join(pasta, n))) for n in nomes))
    cache = _CACHE_ARQUIVO_TS_FOTO
    if cache.get("assinatura") == assinatura:
        return cache.get("caminho")

    candidatos: list[tuple[datetime.datetime, int, str, str, str]] = []
    for nome in nomes:
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:_(\d{6}))?\.json", nome)
        if not m:
            continue
        dia = m.group(1)
        hora = m.group(2) or "000000"
        caminho = os.path.join(pasta, nome)
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except Exception:
            continue
        ts = _max_timestamp_foto_do_json(dados)
        if ts is None:
            ts = datetime.datetime.min
        try:
            match_dia = 1 if ts.date().isoformat() == dia else 0
        except Exception:
            match_dia = 0
        candidatos.append((ts, match_dia, dia, hora, caminho))

    if not candidatos:
        return None

    candidatos.sort()
    escolhido = candidatos[-1][4]
    cache["assinatura"] = assinatura
    cache["caminho"] = escolhido
    return escolhido


def _carregar_json(data_str=None):
    if data_str:
        caminho = _arquivo_do_dia(data_str)
        if not os.path.exists(caminho):
            caminho = _arquivo_mais_recente(data_str)
            if not caminho or not os.path.exists(caminho):
                raise HTTPException(status_code=404, detail="Arquivo do dia não encontrado")
    else:
        caminho = _arquivo_mais_recente_por_timestamp_foto() or _arquivo_mais_recente()
        if not caminho or not os.path.exists(caminho):
            raise HTTPException(status_code=404, detail="Nenhum arquivo JSON encontrado")
    with open(caminho, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            raise HTTPException(status_code=500, detail="Falha ao ler JSON do dia")


def _arquivo_anp_mais_recente(uf: str | None = None, municipio: str | None = None):
    pasta = _processamento_dir()
    if not os.path.exists(pasta):
        return None

    uf_norm = (uf or "").strip().upper() or None
    mun_norm = (municipio or "").strip().lower() or None

    rx = re.compile(
        r"^anp_municipios_(?P<uf>[A-Za-z]{2})_(?P<mun>[-_A-Za-z0-9]+)_(?P<ini>\d{4}-\d{2}-\d{2})_(?P<fim>\d{4}-\d{2}-\d{2})(?:_(?P<hora>\d{6}))?\.json$"
    )

    candidatos: list[tuple[str, str, str, float, str]] = []
    for nome in os.listdir(pasta):
        m = rx.fullmatch(nome)
        if not m:
            continue
        uf_arq = (m.group("uf") or "").upper()
        mun_arq = (m.group("mun") or "").lower()
        if uf_norm and uf_arq != uf_norm:
            continue
        if mun_norm and mun_arq != mun_norm:
            continue
        ini = m.group("ini")
        fim = m.group("fim")
        hora = m.group("hora") or "000000"
        caminho = os.path.join(pasta, nome)
        try:
            mtime = os.path.getmtime(caminho)
        except Exception:
            mtime = 0.0
        candidatos.append((fim, ini, hora, mtime, caminho))

    if not candidatos:
        return None
    candidatos.sort()
    return candidatos[-1][4]

def _preco_para_combustivel(item: object, combustivel: str) -> float | None:
    if not isinstance(item, dict):
        return None
    precos = item.get("precos")
    if not isinstance(precos, dict):
        return None

    def _num(v) -> float | None:
        if isinstance(v, (int, float)) and bool(v) and float(v) == float(v):
            return float(v)
        if isinstance(v, (int, float)) and float(v) == float(v):
            return float(v)
        return None

    c = (combustivel or "").strip().lower()
    if c == "gasolina":
        return _num(precos.get("gasolina_comum")) or _num(precos.get("gasolina_aditivada"))
    if c == "etanol":
        return _num(precos.get("etanol"))
    if c == "diesel":
        return _num(precos.get("diesel_s10")) or _num(precos.get("diesel_s500"))
    return None

def _data_referencia(dados: object) -> str | None:
    ts = _max_timestamp_foto_do_json(dados)
    if ts is not None:
        try:
            return ts.date().isoformat()
        except Exception:
            return None
    return None


@app.get("/api/hoje", tags=["Dados"], summary="Retorna o JSON do dia (ou o mais recente disponível)")
def hoje(x_api_key: str | None = Security(api_key_header)):
    _checar_api_key(x_api_key)
    return _carregar_json()

@app.get("/api/dias", tags=["Dados"], summary="Lista os dias disponíveis no diretório Processamento")
def dias(x_api_key: str | None = Security(api_key_header)):
    _checar_api_key(x_api_key)
    return {"dias": _datas_disponiveis()}

@app.get("/api/dia/{data_str}", tags=["Dados"], summary="Retorna o JSON de um dia específico (YYYY-MM-DD)")
def dia(data_str: str, x_api_key: str | None = Security(api_key_header)):
    _checar_api_key(x_api_key)
    return _carregar_json(data_str)


@app.get("/api/postos", tags=["Postos"], summary="Lista postos do JSON do dia (ou mais recente disponível)")
def postos(combustivel: str | None = None, x_api_key: str | None = Security(api_key_header)):
    _checar_api_key(x_api_key)
    dados = _carregar_json()
    itens = dados.get("postos", [])
    if not isinstance(itens, list):
        return []

    if combustivel is None:
        return itens

    c = combustivel.strip().lower()
    if c not in ("gasolina", "etanol", "diesel"):
        raise HTTPException(status_code=400, detail="Combustível inválido. Use: gasolina, etanol, diesel.")

    def chave(p: object):
        preco = _preco_para_combustivel(p, c)
        if preco is None:
            return (1, 0.0, (p.get("id") if isinstance(p, dict) else "") or "")
        return (0, preco, (p.get("id") if isinstance(p, dict) else "") or "")

    itens_ordenados = list(itens)
    itens_ordenados.sort(key=chave)
    return itens_ordenados


@app.get(
    "/api/postos_resumo",
    tags=["Postos"],
    summary="Lista postos e metadados (data do registro) do JSON do dia (ou mais recente disponível)",
)
def postos_resumo(combustivel: str | None = None, x_api_key: str | None = Security(api_key_header)):
    _checar_api_key(x_api_key)
    dados = _carregar_json()
    itens = dados.get("postos", [])
    if not isinstance(itens, list):
        itens = []

    if combustivel is None:
        c = None
        itens_ordenados = list(itens)
    else:
        c = combustivel.strip().lower()
        if c not in ("gasolina", "etanol", "diesel"):
            raise HTTPException(
                status_code=400, detail="Combustível inválido. Use: gasolina, etanol, diesel."
            )

        def chave(p: object):
            preco = _preco_para_combustivel(p, c)
            if preco is None:
                return (1, 0.0, (p.get("id") if isinstance(p, dict) else "") or "")
            return (0, preco, (p.get("id") if isinstance(p, dict) else "") or "")

        itens_ordenados = list(itens)
        itens_ordenados.sort(key=chave)

    return {
        "data": _data_referencia(dados),
        "total": len(itens_ordenados),
        "combustivel": c,
        "postos": itens_ordenados,
    }


@app.get("/api/postos/{posto_id}", tags=["Postos"], summary="Retorna um posto pelo id (ex.: posto1)")
def posto_por_id(posto_id: str, x_api_key: str | None = Security(api_key_header)):
    _checar_api_key(x_api_key)
    dados = _carregar_json()
    for item in dados.get("postos", []):
        if item.get("id") == posto_id:
            return item
    raise HTTPException(status_code=404, detail="Posto não encontrado")

@app.get("/api/health", tags=["Sistema"], summary="Health check")
def health():
    return {"status": "ok"}


@app.get(
    "/api/anp/municipios",
    tags=["ANP"],
    summary="Retorna o JSON ANP (MUNICIPIOS) mais recente para uf/municipio",
)
def anp_municipios(
    uf: str = "SC", municipio: str = "JOINVILLE", x_api_key: str | None = Security(api_key_header)
):
    _checar_api_key(x_api_key)
    caminho = _arquivo_anp_mais_recente(uf=uf, municipio=municipio)
    if not caminho or not os.path.exists(caminho):
        raise HTTPException(status_code=404, detail="Arquivo ANP não encontrado")
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        raise HTTPException(status_code=500, detail="Falha ao ler JSON ANP")


_JOBS: dict[str, dict[str, object]] = {}
_JOBS_LOCK = threading.Lock()


def _job_get(job_id: str) -> dict[str, object] | None:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def _job_create(tipo: str, comando: list[str]) -> dict[str, object]:
    agora = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "tipo": tipo,
        "status": "running",
        "criado_em": agora,
        "finalizado_em": None,
        "exit_code": None,
        "comando": comando,
        "saida": "",
    }
    with _JOBS_LOCK:
        _JOBS[job_id] = job
    return job


def _job_append_output(job_id: str, texto: str) -> None:
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        atual = str(job.get("saida") or "")
        novo = (atual + texto)[-20000:]
        job["saida"] = novo


def _job_finish(job_id: str, exit_code: int | None) -> None:
    fim = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return
        job["finalizado_em"] = fim
        job["exit_code"] = exit_code
        job["status"] = "done" if exit_code == 0 else "error"


def _iniciar_subprocesso_em_job(
    tipo: str, comando: list[str], cwd: str | None = None, env: dict[str, str] | None = None
) -> dict[str, object]:
    job = _job_create(tipo=tipo, comando=comando)
    job_id = str(job["id"])

    def runner():
        base_env = os.environ.copy()
        if env:
            base_env.update(env)
        try:
            p = subprocess.Popen(
                comando,
                cwd=cwd,
                env=base_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as e:
            _job_append_output(job_id, f"Falha ao iniciar processo: {e}\n")
            _job_finish(job_id, 1)
            return

        try:
            if p.stdout is not None:
                for linha in p.stdout:
                    _job_append_output(job_id, linha)
        except Exception as e:
            _job_append_output(job_id, f"\nFalha ao ler saída: {e}\n")
        finally:
            try:
                p.wait()
            except Exception:
                pass

        _job_finish(job_id, p.returncode)

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    return job


def _sanitizar_nome_arquivo(nome: str) -> str:
    base = os.path.basename(nome or "").strip()
    base = base.replace("\\", "_").replace("/", "_")
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base or "arquivo"


@app.post("/api/processamento/fotos/upload", tags=["Processamento"], summary="Upload de fotos para Processamento/Fotos")
async def upload_fotos(
    files: list[UploadFile] = File(...),
    x_api_key: str | None = Security(api_key_header),
):
    _checar_api_key(x_api_key)
    pasta = _fotos_dir()
    os.makedirs(pasta, exist_ok=True)

    salvos: list[str] = []
    for f in files:
        nome = _sanitizar_nome_arquivo(f.filename or "")
        ext = os.path.splitext(nome)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png"):
            continue
        destino = os.path.join(pasta, nome)
        if os.path.exists(destino):
            base, ext2 = os.path.splitext(nome)
            sufixo = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            destino = os.path.join(pasta, f"{base}_{sufixo}{ext2}")
            nome = os.path.basename(destino)
        payload = await f.read()
        with open(destino, "wb") as out:
            out.write(payload)
        salvos.append(nome)

    return {"arquivos": salvos}


@app.post(
    "/api/processamento/fotos/processar",
    tags=["Processamento"],
    summary="Inicia o processamento das fotos (programa01.py) somente para os arquivos informados",
)
def processar_fotos(
    body: dict = Body(default={}),
    x_api_key: str | None = Security(api_key_header),
):
    _checar_api_key(x_api_key)
    arquivos = body.get("arquivos")
    if arquivos is None:
        arquivos = []
    if not isinstance(arquivos, list) or not all(isinstance(a, str) for a in arquivos):
        raise HTTPException(status_code=400, detail="Campo 'arquivos' inválido")

    proc_dir = _processamento_dir()
    script = os.path.join(proc_dir, "programa01.py")
    if not os.path.exists(script):
        raise HTTPException(status_code=404, detail="programa01.py não encontrado")

    env = {}
    if arquivos:
        env["PROCESSAR_ARQUIVOS"] = ";".join(a.strip() for a in arquivos if a.strip())

    job = _iniciar_subprocesso_em_job(
        tipo="processar_fotos",
        comando=[sys.executable, script],
        cwd=proc_dir,
        env=env,
    )
    return {"job_id": job["id"]}


@app.post(
    "/api/processamento/anp/processar",
    tags=["Processamento"],
    summary="Inicia o processamento ANP (programa02.py)",
)
def processar_anp(
    x_api_key: str | None = Security(api_key_header),
):
    _checar_api_key(x_api_key)
    proc_dir = _processamento_dir()
    script = os.path.join(proc_dir, "programa02.py")
    if not os.path.exists(script):
        raise HTTPException(status_code=404, detail="programa02.py não encontrado")

    job = _iniciar_subprocesso_em_job(
        tipo="processar_anp",
        comando=[sys.executable, script],
        cwd=proc_dir,
        env=None,
    )
    return {"job_id": job["id"]}


@app.get("/api/processamento/jobs/{job_id}", tags=["Processamento"], summary="Consulta status/saída de um job")
def job_status(job_id: str, x_api_key: str | None = Security(api_key_header)):
    _checar_api_key(x_api_key)
    job = _job_get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    return job

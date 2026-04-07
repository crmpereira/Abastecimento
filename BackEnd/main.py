from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
import os
import json
import datetime
import re

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


def _carregar_json(data_str=None):
    if data_str:
        caminho = _arquivo_do_dia(data_str)
        if not os.path.exists(caminho):
            caminho = _arquivo_mais_recente(data_str)
            if not caminho or not os.path.exists(caminho):
                raise HTTPException(status_code=404, detail="Arquivo do dia não encontrado")
    else:
        hoje = datetime.date.today().isoformat()
        caminho = _arquivo_mais_recente(hoje) or _arquivo_mais_recente()
        if not caminho or not os.path.exists(caminho):
            raise HTTPException(status_code=404, detail="Nenhum arquivo JSON encontrado")
    with open(caminho, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            raise HTTPException(status_code=500, detail="Falha ao ler JSON do dia")


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
def postos(x_api_key: str | None = Security(api_key_header)):
    _checar_api_key(x_api_key)
    dados = _carregar_json()
    return dados.get("postos", [])


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

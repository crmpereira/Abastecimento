import google.generativeai as genai
import json
import logging
import os
import re
import time
import datetime
import urllib.parse
import urllib.request
from PIL import Image, ExifTags

# ─────────────────────────────────────────────
# Configurações globais
# ─────────────────────────────────────────────
NOME_ARQUIVO_CHAVE = "gemini_api_key.txt"
MODELO_PADRAO = "models/gemini-2.0-flash"
FAIXA_PRECO_MIN = 2.0
FAIXA_PRECO_MAX = 15.0
ESPERA_ENTRE_FOTOS = 15   # segundos
ESPERA_RATE_LIMIT = 60    # segundos ao receber erro 429
ESPERA_GEOCODE = 1        # segundos entre chamadas de geocodificação


def _env_bool(nome: str) -> bool:
    v = os.getenv(nome, "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def _env_int(nome: str, padrao: int) -> int:
    v = os.getenv(nome, "").strip()
    if not v:
        return padrao
    try:
        return int(v)
    except ValueError:
        return padrao

def _env_str(nome: str) -> str:
    return os.getenv(nome, "").strip()

def _env_lista_str(nome: str) -> list[str]:
    v = os.getenv(nome, "").strip()
    if not v:
        return []
    partes = re.split(r"[,\n;\r\t]+", v)
    return [p.strip() for p in partes if p and p.strip()]


def configurar_log(base_dir: str) -> logging.Logger:
    """
    Configura logger com saída simultânea no terminal e em arquivo 'erros.log'.
    """
    logger = logging.getLogger("extrator_postos")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # Handler de arquivo — apenas WARNING+
    fh = logging.FileHandler(os.path.join(base_dir, "erros.log"), encoding="utf-8")
    fh.setLevel(logging.WARNING)
    fh.setFormatter(fmt)

    # Handler de console — DEBUG+
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ─────────────────────────────────────────────
# Helpers EXIF
# ─────────────────────────────────────────────

def _normalizar_data(valor) -> str | None:
    """Converte datas EXIF 'YYYY:MM:DD HH:MM:SS' para 'YYYY-MM-DD'."""
    if not valor:
        return None
    s = str(valor).strip()
    if not s:
        return None
    if " " in s:
        s = s.split(" ", 1)[0].strip()
    s = s.replace(":", "-", 2)
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def _normalizar_datetime_exif(valor) -> str | None:
    """Converte 'YYYY:MM:DD HH:MM:SS' para 'YYYY-MM-DDTHH:MM:SS'."""
    if not valor:
        return None
    s = str(valor).strip()
    if not s or " " not in s:
        return None
    try:
        data, hora = s.split(" ", 1)
        data_iso = data.replace(":", "-", 2)
        if len(data_iso) == 10 and data_iso[4] == "-" and data_iso[7] == "-":
            return f"{data_iso}T{hora.strip()}"
    except Exception:
        return None
    return None


def _racional_para_float(valor) -> float | None:
    """Converte racionais EXIF (tupla, IFDRational, int, float) para float."""
    try:
        return float(valor)
    except Exception:
        pass
    try:
        num = getattr(valor, "numerator", None)
        den = getattr(valor, "denominator", None)
        if num is not None and den:
            return float(num) / float(den)
    except Exception:
        pass
    if isinstance(valor, tuple) and len(valor) == 2:
        num, den = valor
        if den:
            return float(num) / float(den)
    return None


def _dms_para_decimal(dms, ref) -> float | None:
    """Converte coordenadas DMS do EXIF para graus decimais."""
    if not dms or len(dms) != 3:
        return None
    graus = _racional_para_float(dms[0])
    minutos = _racional_para_float(dms[1])
    segundos = _racional_para_float(dms[2])
    if graus is None or minutos is None or segundos is None:
        return None
    decimal = graus + (minutos / 60.0) + (segundos / 3600.0)
    if str(ref).upper() in ("S", "W"):
        decimal = -decimal
    return round(decimal, 7)


def extrair_localizacao_geografica(caminho_imagem: str) -> dict | None:
    """
    Extrai latitude, longitude e timestamp a partir dos metadados EXIF.
    Prioridade: DateTimeOriginal > DateTime > GPSDateStamp.
    Retorna dict {'lat', 'lon', 'timestamp_foto'} ou None se indisponível.
    """
    try:
        with Image.open(caminho_imagem) as img:
            exif = img.getexif()
            if not exif:
                return None

            data_foto = None
            timestamp_foto = None

            # Busca DateTimeOriginal e DateTime
            for tag_id, tag_name in ExifTags.TAGS.items():
                if tag_name == "DateTimeOriginal":
                    valor = exif.get(tag_id)
                    data_foto = _normalizar_data(valor)
                    timestamp_foto = _normalizar_datetime_exif(valor)
                    break

            if not data_foto:
                for tag_id, tag_name in ExifTags.TAGS.items():
                    if tag_name == "DateTime":
                        valor = exif.get(tag_id)
                        data_foto = _normalizar_data(valor)
                        if not timestamp_foto:
                            timestamp_foto = _normalizar_datetime_exif(valor)
                        break

            # Busca GPSInfo
            gps_tag_id = next(
                (tid for tid, tn in ExifTags.TAGS.items() if tn == "GPSInfo"), None
            )
            if gps_tag_id is None:
                return {"lat": None, "lon": None, "timestamp_foto": timestamp_foto}

            try:
                gps_ifd = exif.get_ifd(gps_tag_id)
            except Exception:
                gps_ifd = exif.get(gps_tag_id)

            if not gps_ifd:
                return {"lat": None, "lon": None, "timestamp_foto": timestamp_foto}

            gps = (
                {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
                if isinstance(gps_ifd, dict)
                else gps_ifd
            )

            lat = _dms_para_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
            lon = _dms_para_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))

            if not data_foto:
                data_foto = _normalizar_data(gps.get("GPSDateStamp"))

            if not timestamp_foto:
                date_stamp = gps.get("GPSDateStamp")
                time_stamp = gps.get("GPSTimeStamp")
                if (
                    date_stamp
                    and time_stamp
                    and isinstance(time_stamp, (list, tuple))
                    and len(time_stamp) == 3
                ):
                    hh = _racional_para_float(time_stamp[0]) or 0.0
                    mm = _racional_para_float(time_stamp[1]) or 0.0
                    ss = _racional_para_float(time_stamp[2]) or 0.0
                    data_iso = str(date_stamp).replace(":", "-", 2)
                    timestamp_foto = f"{data_iso}T{int(hh):02d}:{int(mm):02d}:{int(ss):02d}Z"

            return {
                "lat": lat,
                "lon": lon,
                "timestamp_foto": timestamp_foto or (f"{data_foto}T00:00:00" if data_foto else None),
            }

    except Exception:
        return None

def _extrair_dia_da_foto(caminho_imagem: str, nome_arquivo: str) -> str | None:
    """
    Retorna o dia (YYYY-MM-DD) da foto.
    Prioridade:
    1) EXIF DateTimeOriginal/DateTime
    2) Nome do arquivo (ex.: IMG_20260331_110232.jpg -> 2026-03-31)
    3) mtime do arquivo
    """
    try:
        with Image.open(caminho_imagem) as img:
            exif = img.getexif()
            if exif:
                for tag_id, tag_name in ExifTags.TAGS.items():
                    if tag_name in ("DateTimeOriginal", "DateTime"):
                        valor = exif.get(tag_id)
                        dia = _normalizar_data(valor)
                        if dia:
                            return dia
    except Exception:
        pass

    m = re.search(r"_(\d{8})_", nome_arquivo)
    if m:
        ymd = m.group(1)
        return f"{ymd[0:4]}-{ymd[4:6]}-{ymd[6:8]}"

    try:
        dt = datetime.datetime.fromtimestamp(os.path.getmtime(caminho_imagem)).date()
        return dt.isoformat()
    except Exception:
        return None

def _reverse_geocode_nominatim(
    lat: float,
    lon: float,
    logger: logging.Logger,
    cache: dict[tuple[float, float], dict],
    last_call: list[float],
    espera_geocode: int,
) -> dict | None:
    key = (round(float(lat), 6), round(float(lon), 6))
    if key in cache:
        return cache[key]

    if espera_geocode > 0 and last_call:
        delta = time.monotonic() - last_call[0]
        if delta < espera_geocode:
            time.sleep(espera_geocode - delta)

    qs = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "lat": str(lat),
            "lon": str(lon),
            "addressdetails": "1",
        }
    )
    url = f"https://nominatim.openstreetmap.org/reverse?{qs}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AbasteceAqui/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )

    try:
        last_call[:] = [time.monotonic()]
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"Falha ao buscar endereço (nominatim) para {lat},{lon}: {e}")
        return None

    addr = payload.get("address") if isinstance(payload, dict) else None
    if not isinstance(addr, dict):
        cache[key] = {"display": payload.get("display_name") if isinstance(payload, dict) else None}
        return cache[key]

    rua = addr.get("road") or addr.get("pedestrian") or addr.get("street") or addr.get("path")
    numero = addr.get("house_number")
    bairro = addr.get("suburb") or addr.get("neighbourhood") or addr.get("district")
    cidade = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality")
    uf = addr.get("state")
    cep = addr.get("postcode")
    pais = addr.get("country")

    linha1 = f"{rua}, {numero}" if rua and numero else (rua or None)
    linha2 = " - ".join([p for p in [bairro, cidade] if p])
    display = " | ".join([p for p in [linha1, linha2, uf, cep, pais] if p]) or payload.get("display_name")

    cache[key] = {
        "display": display,
        "rua": rua,
        "numero": numero,
        "bairro": bairro,
        "cidade": cidade,
        "uf": uf,
        "cep": cep,
        "pais": pais,
        "provider": "nominatim",
    }
    return cache[key]


# ─────────────────────────────────────────────
# Configuração do modelo
# ─────────────────────────────────────────────

def normalizar_nome_modelo(model_name: str) -> str:
    """
    Normaliza o nome do modelo Gemini:
    - Usa MODELO_PADRAO se vazio.
    - Garante prefixo 'models/'.
    - Substitui nomes descontinuados por MODELO_PADRAO.
    """
    nome = (model_name or "").strip()
    if not nome:
        return MODELO_PADRAO
    if not nome.startswith("models/"):
        nome = f"models/{nome}"
    if nome in ("models/gemini-1.5-flash", "models/gemini-1.5-pro"):
        return MODELO_PADRAO
    return nome


def carregar_api_key(base_dir: str) -> str:
    """
    Carrega a chave da API do arquivo local 'gemini_api_key.txt'.
    Fallback para variável de ambiente GEMINI_API_KEY.
    """
    caminho = os.path.join(base_dir, NOME_ARQUIVO_CHAVE)
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            for linha in f:
                chave = linha.strip().replace('"', "").replace("'", "")
                if chave:
                    return chave
    return os.getenv("GEMINI_API_KEY", "").strip()


# ─────────────────────────────────────────────
# Extração e validação de preços
# ─────────────────────────────────────────────

def extrair_precos_com_ai(caminho_imagem: str, model) -> dict | None:
    """
    Envia a imagem para o Gemini e interpreta a resposta como JSON de preços.
    Retorna dict com os campos esperados ou None em caso de falha.
    """
    prompt = """
    Você é um extrator de dados de postos de gasolina.
    Analise a imagem e identifique os preços dos combustíveis.

    REGRA DE OURO: O preço DEVE ter 1 dígito à esquerda e 2 à direita do separador (ex: 6.55).
    Ignore números que façam parte do nome do combustível (como o 10 de S10).

    Retorne APENAS um JSON puro, sem texto adicional, neste formato:
    {
      "Gasolina Aditivada": 0.00,
      "Gasolina Comum": 0.00,
      "Etanol": 0.00,
      "Diesel S10": 0.00,
      "Diesel S500": 0.00
    }

    Use null se não encontrar o valor. Não escreva explicações.
    """

    with open(caminho_imagem, "rb") as f:
        image_data = f.read()

    ext = os.path.splitext(caminho_imagem)[1].lower()
    mime_type = "image/png" if ext == ".png" else "image/jpeg"

    response = model.generate_content([
        prompt,
        {"mime_type": mime_type, "data": image_data},
    ])

    return _parse_json_resposta(response.text)


def _parse_json_resposta(texto: str) -> dict | None:
    """
    Remove blocos markdown (```json ... ```) e faz parse seguro do JSON.
    """
    texto = texto.strip()
    # Remove blocos markdown: ```json...``` ou ```...```
    texto = re.sub(r"^```(?:json)?\s*", "", texto)
    texto = re.sub(r"\s*```$", "", texto)
    texto = texto.strip()

    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        # Tenta encontrar JSON dentro de texto lixo
        match = re.search(r"\{.*\}", texto, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def validar_preco(valor) -> float | None:
    """
    Converte e valida um preço. Aceita vírgula como separador decimal.
    Retorna None se estiver fora da faixa esperada para combustíveis BR.
    """
    if valor is None:
        return None
    try:
        if isinstance(valor, str):
            valor = valor.replace(",", ".")
        v = float(valor)
        if FAIXA_PRECO_MIN <= v <= FAIXA_PRECO_MAX:
            return v
        return None
    except (ValueError, TypeError):
        return None


def _precos_para_snake_case(precos_raw: dict) -> dict:
    """
    Converte chaves retornadas pelo modelo para snake_case padronizado
    e valida cada preço pela faixa esperada.
    """
    mapa = {
        "Gasolina Aditivada": "gasolina_aditivada",
        "Gasolina Comum":     "gasolina_comum",
        "Etanol":             "etanol",
        "Diesel S10":         "diesel_s10",
        "Diesel S500":        "diesel_s500",
    }

    saida = {v: None for v in mapa.values()}

    if not isinstance(precos_raw, dict):
        return saida

    for k, v in precos_raw.items():
        alvo = mapa.get(k)
        if alvo:
            saida[alvo] = validar_preco(v)

    return saida

def _precos_ja_padronizados(precos_raw: dict) -> dict | None:
    if not isinstance(precos_raw, dict):
        return None
    chaves = {
        "gasolina_aditivada",
        "gasolina_comum",
        "etanol",
        "diesel_s10",
        "diesel_s500",
    }
    if not any(k in precos_raw for k in chaves):
        return None
    saida = {k: None for k in chaves}
    for k in chaves:
        if k in precos_raw:
            saida[k] = validar_preco(precos_raw.get(k))
    return saida


# ─────────────────────────────────────────────
# Montagem do JSON final
# ─────────────────────────────────────────────

def montar_json_final(processado_em: str, itens_posto: list) -> dict:
    """
    Monta a estrutura final padronizada:
    {
      "processado_em": "...",
      "postos": [ {...}, ... ]
    }
    """
    return {
        "processado_em": processado_em,
        "postos": itens_posto,
    }

def _arquivo_json_mais_recente_com_precos(base_dir: str) -> str | None:
    nomes = []
    for nome in os.listdir(base_dir):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:_\d{6})?\.json", nome):
            nomes.append(nome)
    if not nomes:
        return None

    candidatos = []
    for nome in nomes:
        caminho = os.path.join(base_dir, nome)
        try:
            with open(caminho, "r", encoding="utf-8") as f:
                dados = json.load(f)
        except Exception:
            continue
        postos = dados.get("postos") if isinstance(dados, dict) else None
        if not isinstance(postos, list):
            continue
        tem_preco = False
        for p in postos:
            if not isinstance(p, dict):
                continue
            precos = p.get("precos") or p.get("combustiveis")
            if isinstance(precos, dict) and any(v is not None for v in precos.values()):
                tem_preco = True
                break
        if tem_preco:
            try:
                candidatos.append((os.path.getmtime(caminho), caminho))
            except Exception:
                candidatos.append((0, caminho))

    if not candidatos:
        return None
    candidatos.sort()
    return candidatos[-1][1]

def _carregar_precos_fallback(base_dir: str, logger: logging.Logger) -> dict[str, dict]:
    """
    Carrega um mapa arquivo->precos usando o JSON mais recente no diretório que contenha preços.
    Usado como fallback quando a IA estiver indisponível (ex.: erro 429) ou retornar valores incompletos.
    """
    caminho = os.getenv("PRECOS_FALLBACK_JSON", "").strip()
    if not caminho:
        caminho = _arquivo_json_mais_recente_com_precos(base_dir) or ""
    if not caminho:
        return {}
    if not os.path.isabs(caminho):
        caminho = os.path.join(base_dir, caminho)
    if not os.path.exists(caminho):
        logger.warning(f"PRECOS_FALLBACK_JSON aponta para '{caminho}', mas o arquivo não existe.")
        return {}

    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        logger.warning(f"Falha ao ler fallback de preços em '{caminho}'.")
        return {}

    postos = dados.get("postos") if isinstance(dados, dict) else None
    if not isinstance(postos, list):
        return {}

    mapa: dict[str, dict] = {}
    for p in postos:
        if not isinstance(p, dict):
            continue
        arq = p.get("arquivo")
        if not isinstance(arq, str) or not arq.strip():
            continue
        precos = p.get("precos") or p.get("combustiveis")
        if not isinstance(precos, dict):
            continue
        precos_std = _precos_ja_padronizados(precos) or _precos_para_snake_case(precos)
        if any(v is not None for v in precos_std.values()):
            mapa[arq] = precos_std

    if mapa:
        logger.info(f"Fallback de preços carregado: {os.path.basename(caminho)} ({len(mapa)} itens)")
    return mapa

def _mesclar_precos(base: dict, fallback: dict | None) -> dict:
    if not isinstance(base, dict):
        base = {}
    if not isinstance(fallback, dict):
        return base
    saida = dict(base)
    for k, v in fallback.items():
        if saida.get(k) is None and v is not None:
            saida[k] = v
    return saida

def _limpar_arquivos_do_dia(base_dir: str, dia: str, manter: str, logger: logging.Logger) -> None:
    """
    Mantém apenas um arquivo JSON por dia (YYYY-MM-DD.json).
    Remove arquivos do mesmo dia com sufixo de horário (YYYY-MM-DD_HHMMSS.json).
    """
    padrao = re.compile(rf"{re.escape(dia)}_(\d{{6}})\.json$")
    for nome in os.listdir(base_dir):
        if not padrao.fullmatch(nome):
            continue
        caminho = os.path.join(base_dir, nome)
        if os.path.normcase(caminho) == os.path.normcase(manter):
            continue
        try:
            os.remove(caminho)
            logger.info(f"Removido arquivo antigo do dia: {nome}")
        except Exception:
            pass

# ─────────────────────────────────────────────
# Pipeline principal
# ─────────────────────────────────────────────


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    logger = configurar_log(base_dir)

    pasta_fotos = os.path.join(base_dir, "Fotos")
    agora = datetime.datetime.now().astimezone()
    processado_em = agora.isoformat(timespec="seconds")
    sem_ia = _env_bool("PROCESSAMENTO_SEM_IA")
    arquivos_forcados = _env_lista_str("PROCESSAR_ARQUIVOS")
    espera_entre_fotos = _env_int("ESPERA_ENTRE_FOTOS", ESPERA_ENTRE_FOTOS)
    espera_rate_limit = _env_int("ESPERA_RATE_LIMIT", ESPERA_RATE_LIMIT)
    espera_geocode = _env_int("ESPERA_GEOCODE", ESPERA_GEOCODE)
    geocode_provider = (_env_str("GEOCODE_PROVIDER") or "nominatim").lower()

    ts = agora.strftime("%Y-%m-%d_%H%M%S")
    arquivo_saida_tmp = os.path.join(base_dir, f"{ts}.tmp.json")

    # ── Chave e modelo ──────────────────────────────
    model = None
    if sem_ia:
        logger.warning(
            "PROCESSAMENTO_SEM_IA=1 ativo: IA desativada (somente EXIF). Se houver fallback, os preços serão preenchidos a partir dele."
        )
    else:
        api_key = carregar_api_key(base_dir)
        if not api_key:
            logger.error(f"Chave não encontrada em '{NOME_ARQUIVO_CHAVE}' nem em GEMINI_API_KEY.")
            return

        genai.configure(api_key=api_key)
        model_name = normalizar_nome_modelo(os.getenv("GEMINI_MODEL", "").strip())
        model = genai.GenerativeModel(model_name)
        logger.info(f"Modelo carregado: {model_name}")

    # ── Pasta de fotos ──────────────────────────────
    if not os.path.exists(pasta_fotos):
        logger.error(f"Pasta '{pasta_fotos}' não encontrada.")
        return

    fotos = sorted(f for f in os.listdir(pasta_fotos) if f.lower().endswith((".png", ".jpg", ".jpeg")))
    if arquivos_forcados:
        set_forcados = {a.strip() for a in arquivos_forcados if a and a.strip()}
        fotos = [f for f in fotos if f in set_forcados]
    total = len(fotos)
    logger.info(f"Total de fotos encontradas: {total}")

    if total == 0:
        logger.warning("Nenhuma foto encontrada. Encerrando.")
        return

    if not arquivos_forcados:
        fotos_com_dia: list[tuple[str, str]] = []
        for nome_arq in fotos:
            caminho = os.path.join(pasta_fotos, nome_arq)
            dia_foto = _extrair_dia_da_foto(caminho, nome_arq)
            if dia_foto:
                fotos_com_dia.append((dia_foto, nome_arq))

        if fotos_com_dia:
            dia_alvo = max(d for d, _ in fotos_com_dia)
            fotos = [nome for d, nome in fotos_com_dia if d == dia_alvo]
            logger.info(f"Dia alvo (mais recente): {dia_alvo} | Fotos selecionadas: {len(fotos)}")
        else:
            dia_alvo = agora.strftime("%Y-%m-%d")
            logger.warning("Não foi possível identificar o dia das fotos. Processando todas as imagens encontradas.")
    else:
        dias: list[str] = []
        for nome_arq in fotos:
            caminho = os.path.join(pasta_fotos, nome_arq)
            dia_foto = _extrair_dia_da_foto(caminho, nome_arq)
            if dia_foto:
                dias.append(dia_foto)
        dia_alvo = max(dias) if dias else agora.strftime("%Y-%m-%d")
        logger.info(f"Arquivos forçados: {len(fotos)} | Dia alvo: {dia_alvo}")

    dia = dia_alvo
    arquivo_saida_final = os.path.join(base_dir, f"{dia}.json")
    total = len(fotos)

    lista_postos = []
    precos_fallback_por_arquivo = _carregar_precos_fallback(base_dir, logger)
    if sem_ia and not precos_fallback_por_arquivo:
        logger.error(
            "PROCESSAMENTO_SEM_IA=1 ativo e nenhum fallback de preços encontrado. "
            "Abortando para não gerar JSON sem preços."
        )
        return

    endereco_cache: dict[tuple[float, float], dict] = {}
    last_geocode_call: list[float] = []

    for i, nome_arq in enumerate(fotos, start=1):
        caminho = os.path.join(pasta_fotos, nome_arq)
        logger.info(f"[{i}/{total}] Analisando: {nome_arq}")

        # ── Extração com retry para rate limit ─────
        precos_raw = None
        if not sem_ia and model is not None:
            try:
                precos_raw = extrair_precos_com_ai(caminho, model)
            except Exception as e:
                erro_str = str(e)

                if "429" in erro_str:
                    logger.warning(
                        f"Cota atingida (429). Aguardando {espera_rate_limit}s e tentando novamente..."
                    )
                    time.sleep(espera_rate_limit)
                    try:
                        precos_raw = extrair_precos_com_ai(caminho, model)
                    except Exception as e2:
                        if "429" in str(e2):
                            logger.error(f"Falha novamente por cota (429). Pulando '{nome_arq}'.")
                        else:
                            logger.error(f"Erro inesperado na segunda tentativa de '{nome_arq}': {e2}")

                elif any(code in erro_str for code in ("500", "503")):
                    logger.error(f"Erro no servidor Google ao processar '{nome_arq}': {e}")

                else:
                    logger.error(f"Erro inesperado ao processar '{nome_arq}': {e}")

        # ── Monta item do posto ─────────────────────
        loc = extrair_localizacao_geografica(caminho) or {
            "lat": None, "lon": None, "timestamp_foto": None
        }
        precos_std = _precos_para_snake_case(precos_raw)
        precos_std = _mesclar_precos(precos_std, precos_fallback_por_arquivo.get(nome_arq))

        endereco = None
        lat = loc.get("lat")
        lon = loc.get("lon")
        if (
            geocode_provider == "nominatim"
            and isinstance(lat, (int, float))
            and isinstance(lon, (int, float))
        ):
            endereco = _reverse_geocode_nominatim(
                float(lat),
                float(lon),
                logger,
                endereco_cache,
                last_geocode_call,
                espera_geocode,
            )

        item = {
            "id": f"posto{i}",
            "arquivo": nome_arq,
            "coordenadas": {
                "lat": loc.get("lat"),
                "lon": loc.get("lon"),
                "timestamp_foto": loc.get("timestamp_foto"),
            },
            "endereco": endereco,
            "precos": precos_std,
        }
        lista_postos.append(item)

        if any(v is not None for v in precos_std.values()):
            logger.info(f"   OK: {precos_std}")
        else:
            logger.warning(f"   Sem preços válidos para '{nome_arq}'.")

        # ── Espera entre fotos (exceto após a última) ─
        if not sem_ia and i < total and espera_entre_fotos > 0:
            logger.debug(f"   Aguardando {espera_entre_fotos}s (cota da API)...")
            time.sleep(espera_entre_fotos)

    # ── Salva resultado ─────────────────────────────
    saida = montar_json_final(processado_em, lista_postos)
    with open(arquivo_saida_tmp, "w", encoding="utf-8") as f:
        json.dump(saida, f, indent=4, ensure_ascii=False)

    try:
        os.replace(arquivo_saida_tmp, arquivo_saida_final)
    except Exception:
        try:
            os.remove(arquivo_saida_tmp)
        except Exception:
            pass
        raise

    _limpar_arquivos_do_dia(base_dir, dia, arquivo_saida_final, logger)

    logger.info(f"\nConcluído! Resultado salvo em: {arquivo_saida_final}")


if __name__ == "__main__":
    main()

import google.generativeai as genai
import json
import logging
import os
import re
import time
import datetime
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
    espera_entre_fotos = _env_int("ESPERA_ENTRE_FOTOS", ESPERA_ENTRE_FOTOS)
    espera_rate_limit = _env_int("ESPERA_RATE_LIMIT", ESPERA_RATE_LIMIT)

    # Nome do arquivo inclui horário para evitar sobrescrita
    ts = agora.strftime("%Y-%m-%d_%H%M%S")
    arquivo_saida = os.path.join(base_dir, f"{ts}.json")

    # ── Chave e modelo ──────────────────────────────
    model = None
    if sem_ia:
        logger.warning("PROCESSAMENTO_SEM_IA=1 ativo: preços serão gerados como null (somente EXIF).")
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

    fotos = sorted(
        f for f in os.listdir(pasta_fotos)
        if f.lower().endswith((".png", ".jpg", ".jpeg"))
    )
    total = len(fotos)
    logger.info(f"Total de fotos encontradas: {total}")

    if total == 0:
        logger.warning("Nenhuma foto encontrada. Encerrando.")
        return

    lista_postos = []

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

        item = {
            "id": f"posto{i}",
            "arquivo": nome_arq,
            "coordenadas": {
                "lat": loc.get("lat"),
                "lon": loc.get("lon"),
                "timestamp_foto": loc.get("timestamp_foto"),
            },
            "precos": precos_std,
        }
        lista_postos.append(item)

        if precos_raw:
            logger.info(f"   OK: {precos_std}")
        else:
            logger.warning(f"   Sem preços válidos para '{nome_arq}'.")

        # ── Espera entre fotos (exceto após a última) ─
        if not sem_ia and i < total and espera_entre_fotos > 0:
            logger.debug(f"   Aguardando {espera_entre_fotos}s (cota da API)...")
            time.sleep(espera_entre_fotos)

    # ── Salva resultado ─────────────────────────────
    saida = montar_json_final(processado_em, lista_postos)
    with open(arquivo_saida, "w", encoding="utf-8") as f:
        json.dump(saida, f, indent=4, ensure_ascii=False)

    logger.info(f"\nConcluído! Resultado salvo em: {arquivo_saida}")


if __name__ == "__main__":
    main()

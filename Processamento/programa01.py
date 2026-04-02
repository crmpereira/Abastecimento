import google.generativeai as genai
import json
import os
import time
import datetime
from PIL import Image, ExifTags

NOME_ARQUIVO_CHAVE = "gemini_api_key.txt"
MODELO_PADRAO = "models/gemini-flash-latest"

def _normalizar_data(valor):
    """
    Converte datas EXIF como 'YYYY:MM:DD HH:MM:SS' para 'YYYY-MM-DD'.
    Retorna None quando não for possível normalizar.
    """
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

def _normalizar_datetime_exif(valor):
    """
    Converte 'YYYY:MM:DD HH:MM:SS' para 'YYYY-MM-DDTHH:MM:SS'.
    Retorna None quando não for possível normalizar.
    """
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

def _racional_para_float(valor):
    """
    Converte valores racionais do EXIF (ex.: 123/100) para float.
    Aceita tipos de rational do Pillow, tuplas (num, den) e números já em float/int.
    Retorna None se não for possível converter.
    """
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

def _dms_para_decimal(dms, ref):
    """
    Converte coordenadas em formato DMS (graus, minutos, segundos) do EXIF
    para graus decimais, aplicando sinal conforme referência (N/S, E/W).
    Retorna None se qualquer parte for inválida.
    """
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

def extrair_localizacao_geografica(caminho_imagem: str):
    """
    Extrai latitude, longitude e data da foto a partir dos metadados EXIF.
    - Prioriza DateTimeOriginal; se ausente, tenta DateTime; por fim, GPSDateStamp.
    - Converte GPS DMS para decimal.
    Retorna um dict {'latitude', 'longitude', 'data'} ou None se indisponível.
    """
    try:
        with Image.open(caminho_imagem) as img:
            exif = img.getexif()
            if not exif:
                return None
            data_foto = None
            timestamp_foto = None
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
            gps_tag_id = None
            for tag_id, tag_name in ExifTags.TAGS.items():
                if tag_name == "GPSInfo":
                    gps_tag_id = tag_id
                    break
            if gps_tag_id is None:
                lat = None
                lon = None
                return {"lat": lat, "lon": lon, "timestamp_foto": timestamp_foto or None}
            try:
                gps_ifd = exif.get_ifd(gps_tag_id)
            except Exception:
                gps_ifd = exif.get(gps_tag_id)
            if not gps_ifd:
                return {"lat": None, "lon": None, "timestamp_foto": timestamp_foto or None}

            gps = {}
            if isinstance(gps_ifd, dict):
                for k, v in gps_ifd.items():
                    gps[ExifTags.GPSTAGS.get(k, k)] = v
            else:
                gps = gps_ifd

            lat = _dms_para_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
            lon = _dms_para_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
            if lat is None and lon is None:
                return {"lat": None, "lon": None, "timestamp_foto": timestamp_foto or None}
            if not data_foto:
                data_foto = _normalizar_data(gps.get("GPSDateStamp"))
            if not timestamp_foto:
                date_stamp = gps.get("GPSDateStamp")
                time_stamp = gps.get("GPSTimeStamp")
                if date_stamp and time_stamp and isinstance(time_stamp, (list, tuple)) and len(time_stamp) == 3:
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

def normalizar_nome_modelo(model_name: str) -> str:
    """
    Normaliza o nome do modelo Gemini:
    - Usa MODELO_PADRAO se vazio.
    - Garante prefixo 'models/'.
    - Substitui nomes antigos por MODELO_PADRAO.
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
    Carrega a chave da API do arquivo local 'gemini_api_key.txt' na pasta do script.
    Se não existir ou estiver vazio, tenta a variável de ambiente GEMINI_API_KEY.
    Retorna a chave como string (pode ser vazia).
    """
    caminho = os.path.join(base_dir, NOME_ARQUIVO_CHAVE)
    if os.path.exists(caminho):
        with open(caminho, "r", encoding="utf-8") as f:
            for linha in f:
                # Remove espaços, quebras de linha e ASPAS acidentais
                chave = linha.strip().replace('"', '').replace("'", "")
                if chave:
                    return chave
    return os.getenv("GEMINI_API_KEY", "").strip()

def extrair_precos_com_ai(caminho_imagem, model):
    """
    Envia a imagem para o modelo Gemini com um prompt restritivo e tenta
    interpretar a resposta como JSON contendo preços por combustível.
    Retorna um dict com campos esperados ou None em caso de falha/parse inválido.
    """
    prompt = """
    Você é um extrator de dados de postos de gasolina. 
    Analise a imagem e identifique os preços.
    REGRA DE OURO: O preço DEVE ter 1 dígito à esquerda e 2 dígitos à direita do ponto/vírgula (ex: 6.55).
    Ignore números que façam parte do nome do combustível (como o 10 de S10).
    
    Retorne APENAS um JSON puro neste formato:
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
        {"mime_type": mime_type, "data": image_data}
    ])

    # Limpeza robusta do JSON
    texto = response.text.strip()
    if texto.startswith("```json"):
        texto = texto.replace("```json", "", 1).replace("```", "", 1).strip()
    elif texto.startswith("```"):
        texto = texto.replace("```", "", 2).strip()
    
    try:
        return json.loads(texto)
    except Exception as e:
        print(f"   [AVISO] Erro ao converter JSON: {e} | Resposta: {texto[:50]}...")
        return None

def _precos_para_snake_case(precos_raw: dict) -> dict:
    """
    Converte as chaves retornadas pelo modelo para snake_case padronizado.
    """
    if not isinstance(precos_raw, dict):
        return {
            "gasolina_aditivada": None,
            "gasolina_comum": None,
            "etanol": None,
            "diesel_s10": None,
            "diesel_s500": None,
        }
    mapa = {
        "Gasolina Aditivada": "gasolina_aditivada",
        "Gasolina Comum": "gasolina_comum",
        "Etanol": "etanol",
        "Diesel S10": "diesel_s10",
        "Diesel S500": "diesel_s500",
    }
    saida = {}
    for k_std in mapa.values():
        saida[k_std] = None
    for k, v in precos_raw.items():
        alvo = mapa.get(k)
        if alvo:
            saida[alvo] = v
    return saida

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

def main():
    """
    Pipeline principal:
    - Define paths e nome do arquivo de saída diário (YYYY-MM-DD.json).
    - Carrega chave, configura modelo e lista fotos.
    - Para cada foto: extrai localização EXIF, consulta a IA para preços e grava no dict.
    - Salva o JSON final com timestamp de processamento.
    """
    base_dir = os.path.dirname(os.path.abspath(__file__))
    pasta_fotos = os.path.join(base_dir, "Fotos")
    agora = datetime.datetime.now().astimezone()
    data_do_dia = agora.date().isoformat()
    arquivo_saida = os.path.join(base_dir, f"{data_do_dia}.json")
    processado_em = agora.isoformat(timespec="seconds")
    
    api_key = carregar_api_key(base_dir)
    if not api_key:
        print(f"[ERRO] Chave não encontrada em {NOME_ARQUIVO_CHAVE}")
        return

    genai.configure(api_key=api_key)
    model_name = normalizar_nome_modelo(os.getenv("GEMINI_MODEL", "").strip())
    model = genai.GenerativeModel(model_name)
    time.sleep(5)

    if not os.path.exists(pasta_fotos):
        print(f"[ERRO] Pasta '{pasta_fotos}' não encontrada.")
        return

    fotos = [f for f in os.listdir(pasta_fotos) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    print(f"Total de fotos: {len(fotos)}")

    lista_postos = []

    for i, nome_arq in enumerate(fotos, start=1):
        caminho = os.path.join(pasta_fotos, nome_arq)
        print(f"[{i+1}/{len(fotos)}] Analisando: {nome_arq}...")

        precos_raw = None
        try:
            precos_raw = extrair_precos_com_ai(caminho, model)
        except Exception as e:
            if "429" in str(e):
                print("Cota atingida, aguardando 60s para tentar novamente...")
                time.sleep(60)
                try:
                    precos_raw = extrair_precos_com_ai(caminho, model)
                except Exception as e2:
                    if "429" in str(e2):
                        print("   Falha novamente por cota (429). Pulando esta foto.")
                    else:
                        print(f"   ERRO na foto {nome_arq}: {e2}")
            else:
                print(f"   ERRO na foto {nome_arq}: {e}")

        id_posto = f"posto{i}"
        loc = extrair_localizacao_geografica(caminho) or {"lat": None, "lon": None, "timestamp_foto": None}
        precos_std = _precos_para_snake_case(precos_raw)
        item = {
            "id": id_posto,
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
            print(f"   OK: {precos_std}")
        else:
            print("   Sem preços (falha na extração).")

        if i < len(fotos) - 1:
            print("   Aguardando 15s (Cota API)...")
            time.sleep(15)

    saida = montar_json_final(processado_em, lista_postos)
    with open(arquivo_saida, 'w', encoding='utf-8') as f:
        json.dump(saida, f, indent=4, ensure_ascii=False)

    print(f"\nConcluido! Resultado em: {arquivo_saida}")

if __name__ == "__main__":
    main()

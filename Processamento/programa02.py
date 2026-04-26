import datetime
import io
import json
import os
import re
import urllib.parse
import urllib.request
import unicodedata
import zipfile
import xml.etree.ElementTree as ET

ANP_BASE_URL = (
    "https://www.gov.br/anp/pt-br/assuntos/precos-e-defesa-da-concorrencia/precos/"
    "arquivos-lpc/2026/"
)
ANP_PREFIXO_ARQUIVO = "resumo_semanal_lpc_"

UF_ALVO = "SC"
ESTADO_ALVO = "SANTA CATARINA"
MUNICIPIO_ALVO = "JOINVILLE"
SCHEMA_VERSION = 2
PRODUTOS_EXCLUIDOS = {"GLP", "GNV"}


def _agora_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _download(url: str) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "AbasteceAqui/1.0",
            "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()

def _resolver_url_xlsx(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if "view.officeapps.live.com" not in u:
        return u
    try:
        parsed = urllib.parse.urlparse(u)
        qs = urllib.parse.parse_qs(parsed.query)
        src = qs.get("src", [None])[0]
        if not src:
            return u
        return urllib.parse.unquote(src)
    except Exception:
        return u

def _extrair_periodo_do_nome(url: str) -> tuple[str, str] | None:
    m = re.search(r"resumo_semanal_lpc_(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})\.xlsx", url)
    if not m:
        return None
    return (m.group(1), m.group(2))

def _listar_urls_xlsx_anp(base_url: str) -> list[str]:
    req = urllib.request.Request(
        base_url,
        headers={"User-Agent": "AbasteceAqui/1.0", "Accept": "text/html,*/*"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    urls = set()
    for m in re.finditer(r'href="([^"]+)"', html, flags=re.IGNORECASE):
        href = m.group(1)
        if ".xlsx" not in href.lower():
            continue
        if ANP_PREFIXO_ARQUIVO not in href:
            continue
        abs_url = urllib.parse.urljoin(base_url, href)
        if ANP_PREFIXO_ARQUIVO in abs_url and abs_url.lower().endswith(".xlsx"):
            urls.add(abs_url)
    return sorted(urls)

def _ultima_saida_processada(base_dir: str) -> tuple[str | None, str | None, int | None]:
    """
    Retorna (fonte_url, periodo_fim, schema_version) do JSON mais recente gerado pelo programa02.
    """
    candidatos = []
    for nome in os.listdir(base_dir):
        if not re.fullmatch(r"anp_municipios_sc_joinville(?:_\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})?\.json", nome):
            continue
        caminho = os.path.join(base_dir, nome)
        try:
            mtime = os.path.getmtime(caminho)
        except Exception:
            mtime = 0
        candidatos.append((mtime, caminho))
    if not candidatos:
        return (None, None, None)
    candidatos.sort()
    caminho = candidatos[-1][1]
    try:
        with open(caminho, "r", encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        return (None, None, None)
    if not isinstance(dados, dict):
        return (None, None, None)
    fonte = dados.get("fonte_url")
    periodo = dados.get("periodo")
    fim = periodo.get("fim") if isinstance(periodo, dict) else None
    schema = dados.get("schema_version")
    schema_int = schema if isinstance(schema, int) else None
    return (fonte if isinstance(fonte, str) else None, fim if isinstance(fim, str) else None, schema_int)

def _descobrir_url_mais_recente(base_dir: str) -> str | None:
    urls = _listar_urls_xlsx_anp(ANP_BASE_URL)
    candidatos: list[tuple[str, str, str]] = []
    for u in urls:
        p = _extrair_periodo_do_nome(u)
        if not p:
            continue
        ini, fim = p
        candidatos.append((fim, ini, u))
    if not candidatos:
        return None
    candidatos.sort()
    candidatos.reverse()
    return candidatos[0][2]

def _descobrir_url_mais_recente_diferente(base_dir: str) -> str | None:
    fonte_antiga, fim_antigo, _schema_antigo = _ultima_saida_processada(base_dir)
    urls = _listar_urls_xlsx_anp(ANP_BASE_URL)
    candidatos: list[tuple[str, str, str]] = []
    for u in urls:
        p = _extrair_periodo_do_nome(u)
        if not p:
            continue
        ini, fim = p
        candidatos.append((fim, ini, u))
    if not candidatos:
        return None
    candidatos.sort()
    candidatos.reverse()
    for fim, ini, u in candidatos:
        if fonte_antiga and u == fonte_antiga:
            continue
        if fim_antigo and fim == fim_antigo:
            continue
        return u
    return None


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(data)
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    out: list[str] = []
    for si in root.findall("s:si", ns):
        texts: list[str] = []
        for t in si.findall(".//s:t", ns):
            if t.text:
                texts.append(t.text)
        out.append("".join(texts))
    return out


def _col_letters_to_index(col: str) -> int:
    n = 0
    for ch in col:
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def _cell_ref_to_index(cell_ref: str) -> int:
    m = re.match(r"^([A-Z]+)\d+$", cell_ref or "")
    if not m:
        return -1
    return _col_letters_to_index(m.group(1))


def _parse_cell_value(c: ET.Element, shared: list[str], ns: dict[str, str]):
    t = c.get("t")
    v = c.find("s:v", ns)
    if t == "s":
        if v is None or v.text is None:
            return None
        try:
            idx = int(v.text)
        except Exception:
            return None
        return shared[idx] if 0 <= idx < len(shared) else None
    if t == "inlineStr":
        tt = c.find(".//s:t", ns)
        return tt.text if tt is not None else None
    if v is None or v.text is None:
        return None
    txt = v.text.strip()
    if not txt:
        return None
    try:
        if "." in txt:
            return float(txt)
        return int(txt)
    except Exception:
        return txt


def _iter_sheet_rows(zf: zipfile.ZipFile, sheet_path: str, shared: list[str]):
    data = zf.read(sheet_path)
    root = ET.fromstring(data)
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    sheet_data = root.find("s:sheetData", ns)
    if sheet_data is None:
        return
    for row in sheet_data.findall("s:row", ns):
        values: dict[int, object] = {}
        max_idx = -1
        for c in row.findall("s:c", ns):
            r = c.get("r") or ""
            idx = _cell_ref_to_index(r)
            if idx < 0:
                continue
            val = _parse_cell_value(c, shared, ns)
            if val is None:
                continue
            values[idx] = val
            if idx > max_idx:
                max_idx = idx
        if max_idx < 0:
            yield []
            continue
        out = [None] * (max_idx + 1)
        for i, v in values.items():
            if 0 <= i < len(out):
                out[i] = v
        yield out


def _sheet_names(zf: zipfile.ZipFile) -> dict[str, str]:
    data = zf.read("xl/workbook.xml")
    root = ET.fromstring(data)
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    sheets = root.find("s:sheets", ns)
    if sheets is None:
        return {}
    out: dict[str, str] = {}
    for s in sheets.findall("s:sheet", ns):
        name = s.get("name")
        sheet_id = s.get("sheetId")
        if name and sheet_id:
            out[f"xl/worksheets/sheet{sheet_id}.xml"] = name
    return out


def _normalizar_header(v: object) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _norm_key(s: str) -> str:
    s = (s or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"\s+", " ", s)
    return s.upper()


def _encontrar_planilha_e_header(zf: zipfile.ZipFile, shared: list[str]):
    nomes = _sheet_names(zf)
    sheet_files = [n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")]
    candidatos: list[tuple[int, str, int, list[str]]] = []
    for sheet_path in sheet_files:
        score = 0
        header_row_idx = -1
        header: list[str] = []
        it = _iter_sheet_rows(zf, sheet_path, shared)
        for i in range(0, 120):
            try:
                row = next(it)
            except StopIteration:
                break
            row_norm = [_normalizar_header(x) for x in row]
            keys = [_norm_key(x) for x in row_norm]
            cols = set(keys)
            if "ESTADO" in cols or "UF" in cols or "ESTADOS" in cols:
                score = 1
                if "MUNICIPIO" in cols:
                    score += 3
                if "PRODUTO" in cols:
                    score += 2
                if any("PRECO" in c for c in cols):
                    score += 2
                header_row_idx = i
                header = row_norm
                break
        if score > 0 and header_row_idx >= 0:
            candidatos.append((score, sheet_path, header_row_idx, header))
    if not candidatos:
        return None
    candidatos.sort()
    score, sheet_path, header_row_idx, header = candidatos[-1]
    return {
        "sheet_path": sheet_path,
        "sheet_name": nomes.get(sheet_path) or os.path.basename(sheet_path),
        "header_row_idx": header_row_idx,
        "header": header,
        "score": score,
    }

def _sheet_path_por_nome(zf: zipfile.ZipFile, nome_alvo: str) -> str | None:
    alvo = _norm_key(nome_alvo)
    for path, name in _sheet_names(zf).items():
        if _norm_key(name) == alvo:
            return path
    return None

def _encontrar_header_em_planilha(zf: zipfile.ZipFile, shared: list[str], sheet_path: str):
    it = _iter_sheet_rows(zf, sheet_path, shared)
    for i in range(0, 80):
        try:
            row = next(it)
        except StopIteration:
            break
        row_norm = [_normalizar_header(x) for x in row]
        keys = [_norm_key(x) for x in row_norm]
        cols = set(keys)
        if "ESTADO" in cols and "MUNICIPIO" in cols and "PRODUTO" in cols:
            return {"header_row_idx": i, "header": row_norm}
    return None


def _infer_periodo(url: str) -> dict | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})\.xlsx", url)
    if not m:
        return None
    return {"inicio": m.group(1), "fim": m.group(2)}

def _excel_serial_to_date_iso(valor: object) -> str | None:
    if not isinstance(valor, (int, float)):
        return None
    if not (valor == valor):
        return None
    dias = int(valor)
    if dias <= 0:
        return None
    base = datetime.date(1899, 12, 30)
    try:
        d = base + datetime.timedelta(days=dias)
    except Exception:
        return None
    return d.isoformat()


def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    fonte_antiga, _fim_antigo, schema_antigo = _ultima_saida_processada(base_dir)
    reprocessar = (os.getenv("ANP_REPROCESSAR") or "").strip().lower() in ("1", "true", "sim", "yes")
    precisa_reprocessar = schema_antigo is None or schema_antigo < SCHEMA_VERSION

    url = _resolver_url_xlsx((os.getenv("ANP_XLSX_URL") or "").strip())
    if not url:
        if reprocessar or precisa_reprocessar:
            url = fonte_antiga or _descobrir_url_mais_recente(base_dir) or ""
        else:
            url = _descobrir_url_mais_recente_diferente(base_dir) or ""
    if not url:
        raise SystemExit("Nenhum XLSX encontrado para processar.")

    xlsx = _download(url)
    zf = zipfile.ZipFile(io.BytesIO(xlsx))
    shared = _xlsx_shared_strings(zf)

    sheet_path = _sheet_path_por_nome(zf, "MUNICIPIOS")
    if not sheet_path:
        raise SystemExit("Não foi possível localizar a guia 'MUNICIPIOS' no XLSX.")

    meta_header = _encontrar_header_em_planilha(zf, shared, sheet_path)
    if not meta_header:
        raise SystemExit("Não foi possível localizar o header na guia 'MUNICIPIOS'.")

    header = meta_header["header"]
    header_keys = [_norm_key(h) for h in header]

    try:
        estado_idx = header_keys.index("ESTADO")
    except ValueError:
        raise SystemExit("Guia 'MUNICIPIOS' não contém coluna ESTADO.")

    try:
        municipio_idx = header_keys.index("MUNICIPIO")
    except ValueError:
        raise SystemExit("Guia 'MUNICIPIOS' não contém coluna MUNICÍPIO.")

    def _idx(nome: str) -> int | None:
        k = _norm_key(nome)
        try:
            return header_keys.index(k)
        except ValueError:
            return None

    produto_idx = _idx("PRODUTO")
    unidade_idx = _idx("UNIDADE DE MEDIDA")
    postos_idx = _idx("NÚMERO DE POSTOS PESQUISADOS")
    preco_medio_idx = _idx("PREÇO MÉDIO REVENDA")
    preco_min_idx = _idx("PREÇO MÍNIMO REVENDA")
    preco_max_idx = _idx("PREÇO MÁXIMO REVENDA")
    desvio_idx = _idx("DESVIO PADRÃO REVENDA")
    cv_idx = _idx("COEF DE VARIAÇÃO REVENDA")
    data_ini_idx = _idx("DATA INICIAL")
    data_fim_idx = _idx("DATA FINAL")

    produtos = []
    for idx, row in enumerate(_iter_sheet_rows(zf, sheet_path, shared)):
        if idx <= meta_header["header_row_idx"]:
            continue
        if not row or all(v is None or str(v).strip() == "" for v in row):
            continue

        estado_val = row[estado_idx] if estado_idx < len(row) else None
        estado_str = _norm_key(str(estado_val)) if estado_val is not None else ""
        if estado_str != _norm_key(ESTADO_ALVO):
            continue

        municipio_val = row[municipio_idx] if municipio_idx < len(row) else None
        municipio_str = _norm_key(str(municipio_val)) if municipio_val is not None else ""
        if municipio_str != _norm_key(MUNICIPIO_ALVO):
            continue

        produto_raw = row[produto_idx] if produto_idx is not None and produto_idx < len(row) else None
        produto_nome = str(produto_raw).strip() if produto_raw is not None else ""
        produto_norm = _norm_key(produto_nome)
        if produto_norm in PRODUTOS_EXCLUIDOS or "GLP" in produto_norm or "GNV" in produto_norm:
            continue

        unidade = row[unidade_idx] if unidade_idx is not None and unidade_idx < len(row) else None
        postos = row[postos_idx] if postos_idx is not None and postos_idx < len(row) else None
        preco_medio = row[preco_medio_idx] if preco_medio_idx is not None and preco_medio_idx < len(row) else None
        preco_min = row[preco_min_idx] if preco_min_idx is not None and preco_min_idx < len(row) else None
        preco_max = row[preco_max_idx] if preco_max_idx is not None and preco_max_idx < len(row) else None
        desvio = row[desvio_idx] if desvio_idx is not None and desvio_idx < len(row) else None
        cv = row[cv_idx] if cv_idx is not None and cv_idx < len(row) else None
        data_ini = row[data_ini_idx] if data_ini_idx is not None and data_ini_idx < len(row) else None
        data_fim = row[data_fim_idx] if data_fim_idx is not None and data_fim_idx < len(row) else None

        def _num(v):
            if isinstance(v, (int, float)) and v == v:
                return float(v)
            if isinstance(v, str):
                s = v.strip().replace(",", ".")
                try:
                    return float(s)
                except Exception:
                    return None
            return None

        def _int(v):
            n = _num(v)
            if n is None:
                return None
            try:
                return int(round(n))
            except Exception:
                return None

        produtos.append(
            {
                "produto": produto_nome,
                "unidade": str(unidade).strip() if unidade is not None else None,
                "postos_pesquisados": _int(postos),
                "preco_medio": _num(preco_medio),
                "preco_min": _num(preco_min),
                "preco_max": _num(preco_max),
                "desvio_padrao": _num(desvio),
                "coef_variacao": _num(cv),
                "data_inicial": _excel_serial_to_date_iso(data_ini),
                "data_final": _excel_serial_to_date_iso(data_fim),
            }
        )

    periodo = _infer_periodo(url)
    out = {
        "schema_version": SCHEMA_VERSION,
        "fonte_url": url,
        "gerado_em": _agora_iso(),
        "uf": UF_ALVO,
        "estado": ESTADO_ALVO,
        "municipio": MUNICIPIO_ALVO,
        "periodo": periodo,
        "planilha": "MUNICIPIOS",
        "total_produtos": len(produtos),
        "produtos": produtos,
    }

    sufixo = ""
    if periodo:
        sufixo = f"_{periodo['inicio']}_{periodo['fim']}"
    caminho_saida = os.path.join(base_dir, f"anp_municipios_sc_joinville{sufixo}.json")
    with open(caminho_saida, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(caminho_saida)


if __name__ == "__main__":
    main()


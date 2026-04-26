# AbasteceAqui

Projeto com 3 partes:

- Processamento: lê fotos de bombas/placas de preços, extrai coordenadas/data via EXIF e consulta IA (Gemini) para obter os preços; gera um JSON diário.
- Processamento (ANP): baixa a planilha semanal da ANP, filtra por UF/município e gera um JSON para consumo no app.
- BackEnd: API (FastAPI) que serve os dados do JSON diário.
- FrontEnd: app (Expo/React Native) que consome a API e lista os postos.

## Estrutura

- Processamento/
  - programa01.py
  - programa02.py
  - Fotos/ (coloque aqui as imagens .jpg/.jpeg/.png)
  - gemini_api_key.txt (chave do Gemini)
  - YYYY-MM-DD.json (saída gerada pelo processamento)
  - anp_municipios_<UF>_<MUNICIPIO>_<YYYY-MM-DD>_<YYYY-MM-DD>.json (saída gerada do ANP)
- BackEnd/
  - main.py
  - requirements.txt
- FrontEnd/
  - app Expo/React Native

## Processamento (geração do JSON)

1) Dependências (Python):

```bash
pip install google-generativeai Pillow
```

2) Chave do Gemini:

- Crie o arquivo Processamento/gemini_api_key.txt contendo apenas a sua chave.

3) Imagens:

- Coloque as fotos em Processamento/Fotos/.

4) Executar:

```bash
py Processamento/programa01.py
```

Saída:

- O script cria um arquivo Processamento/YYYY-MM-DD.json com o formato:
  - processado_em (timestamp ISO)
  - postos: lista com id, arquivo, coordenadas (lat/lon/timestamp_foto) e precos (gasolina_comum, gasolina_aditivada, etanol, diesel_s10, diesel_s500)

Observações:

- O modelo do Gemini pode ser alterado via variável de ambiente GEMINI_MODEL.

### Por que fotos? (decisão de processamento)

- Postos não possuem uma API pública e padronizada para preços.
- Para ter cobertura universal, o processo utiliza fotos de placas/bombas e extrai:
  - Coordenadas e data/hora via metadados EXIF.
  - Preços via IA (Gemini), gerando um JSON diário consumido pelo BackEnd/FrontEnd.
- Benefícios: funciona com qualquer posto e não depende de integração proprietária.
- Limitações: qualidade da foto (iluminação/ângulo), custos/limites da IA e tempo de processamento.
- Mitigações implementadas:
  - Esperas configuráveis entre fotos e em caso de limite (429) para reduzir erros.
  - Execução sem IA para testes: se definir `PROCESSAMENTO_SEM_IA=1`, os preços saem como `null` (gera somente EXIF).

Variáveis úteis:

```bash
# Define o modelo Gemini usado na extração
GEMINI_MODEL=gemini-1.5-flash

# Desativa a IA (somente EXIF, preços = null) — útil para testes
PROCESSAMENTO_SEM_IA=1

# Processa SOMENTE os arquivos listados (separados por ; , ou quebra de linha)
# Ex.: PROCESSAR_ARQUIVOS="IMG_001.jpg;IMG_002.jpg"
PROCESSAR_ARQUIVOS=
```

## Processamento ANP (MUNICÍPIOS)

Executar:

```bash
py Processamento/programa02.py
```

Observações:

- O script tenta descobrir automaticamente o XLSX mais recente da ANP.
- Se precisar forçar uma URL específica do XLSX, use:

```bash
ANP_XLSX_URL=https://www.gov.br/anp/.../resumo_semanal_lpc_YYYY-MM-DD-YYYY-MM-DD.xlsx
```

## BackEnd (FastAPI + Swagger)

1) Instalar dependências:

```bash
pip install -r BackEnd/requirements.txt
```

2) Rodar:

```bash
py -m uvicorn BackEnd.main:app --reload --host 0.0.0.0 --port 8000
```

3) Swagger:

- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

4) API Key (opcional):

- Se você definir a variável de ambiente ABASTECEAQUI_API_KEY, a API passa a exigir o header:
  - x-api-key: <sua-chave>
- No Swagger, use o botão Authorize e informe a chave.

Endpoints principais:

- GET /api/postos
- GET /api/postos/{posto_id}
- GET /api/hoje
- GET /api/dias
- GET /api/dia/{data_str}
- GET /api/anp/municipios

Endpoints de processamento (executam os scripts Python no servidor):

- POST /api/processamento/fotos/upload
- POST /api/processamento/fotos/processar
- POST /api/processamento/anp/processar
- GET /api/processamento/jobs/{job_id}

## FrontEnd (Expo)

1) Instalar dependências:

```bash
cd FrontEnd
npm install
```

2) Rodar no Web:

```bash
npm run web
```

3) Rodar no celular:

- Inicie o app (Expo Go) e aponte para o mesmo servidor do Metro.
- O FrontEnd tenta detectar automaticamente o IP do PC para montar a URL da API.

Configurações opcionais (FrontEnd):

- EXPO_PUBLIC_API_BASE_URL: base da API (ex.: http://127.0.0.1:8000)
- EXPO_PUBLIC_API_KEY: enviada como x-api-key para a API

### Tela de Processamentos (Fotos + ANP)

- Existe uma tela “Processamentos” (acessível pelo ícone de engrenagem na tela de postos).
- Restrição: o ícone de engrenagem só aparece para o usuário `cesar.pereiram@gmail.com`.
- Fotos:
  - No Web (Windows), permite selecionar uma pasta, marcar arquivos (ou marcar todos) e enviar somente os selecionados.
  - Ao executar, o BackEnd faz upload para `Processamento/Fotos/` e roda `programa01.py` apenas para os arquivos selecionados.
- ANP:
  - Botão “Processar ANP” que roda `programa02.py` no BackEnd.

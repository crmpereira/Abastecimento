# AbasteceAqui

Projeto com 3 partes:

- Processamento: lê fotos de bombas/placas de preços, extrai coordenadas/data via EXIF e consulta IA (Gemini) para obter os preços; gera um JSON diário.
- BackEnd: API (FastAPI) que serve os dados do JSON diário.
- FrontEnd: app (Expo/React Native) que consome a API e lista os postos.

## Estrutura

- Processamento/
  - programa01.py
  - Fotos/ (coloque aqui as imagens .jpg/.jpeg/.png)
  - gemini_api_key.txt (chave do Gemini)
  - YYYY-MM-DD.json (saída gerada pelo processamento)
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

## FrontEnd (Expo)

1) Instalar dependências:

```bash
cd FrontEnd
npm install
```

2) Rodar no Web:

```bash
npm run web -- --port 19007
```

3) Rodar no celular:

- Inicie o app (Expo Go) e aponte para o mesmo servidor do Metro.
- O FrontEnd tenta detectar automaticamente o IP do PC para montar a URL da API.

Configurações opcionais (FrontEnd):

- EXPO_PUBLIC_API_BASE_URL: base da API (ex.: http://127.0.0.1:8000)
- EXPO_PUBLIC_API_KEY: enviada como x-api-key para a API

# ARTEMIS Deployment

ARTEMIS has two services:

- Python API: `artemis_api.py`
- React frontend: `artemis-react`

## 1. Deploy Python API

Use Render, Railway, Fly.io, or another Python web service.

Recommended settings:

- Root directory: project root
- Build command: `pip install -r requirements.txt`
- Start command: `python artemis_api.py`
- Environment variables:
  - `HOST=0.0.0.0`
  - `PORT` should usually be provided by the platform automatically
  - `ARTEMIS_API_KEY=...` or `OPENAI_API_KEY=...` if AI modes are needed
  - `ARTEMIS_MODEL=gpt-5.4` or `OPENAI_MODEL=gpt-5.4`
  - `ARTEMIS_BASE_URL=...` or `OPENAI_BASE_URL=...` when using an OpenAI-compatible provider
  - `ARTEMIS_LLM_API_STYLE=chat` for most OpenAI-compatible providers; use `responses` for OpenAI Responses API
  - `CORS_ORIGIN=*` for quick team testing

OpenAI-compatible examples:

```text
# DeepSeek
ARTEMIS_API_KEY=sk-...
ARTEMIS_MODEL=deepseek-chat
ARTEMIS_BASE_URL=https://api.deepseek.com
ARTEMIS_LLM_API_STYLE=chat

# OpenRouter
ARTEMIS_API_KEY=sk-or-...
ARTEMIS_MODEL=openai/gpt-4o-mini
ARTEMIS_BASE_URL=https://openrouter.ai/api/v1
ARTEMIS_LLM_API_STYLE=chat
```

After deployment, copy the API URL, for example:

```text
https://artemis-api.example.com
```

Test:

```text
https://artemis-api.example.com/api/health
```

It should return:

```json
{"ok": true, "service": "artemis-python"}
```

## 2. Deploy React Frontend

Use Vercel, Netlify, Cloudflare Pages, or another static frontend host.

Recommended settings:

- Root directory: `artemis-react`
- Build command: `npm run build`
- Output directory: `dist`
- Environment variables:
  - `VITE_API_BASE=https://your-python-api-url`

Redeploy after setting `VITE_API_BASE`.

## 3. Local Development

Terminal 1:

```bash
python artemis_api.py
```

Terminal 2:

```bash
cd artemis-react
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173/
```

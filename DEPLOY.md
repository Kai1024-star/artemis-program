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
  - `OPENAI_API_KEY=...` if AI modes are needed
  - `OPENAI_MODEL=gpt-5.4`
  - `CORS_ORIGIN=*` for quick team testing

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

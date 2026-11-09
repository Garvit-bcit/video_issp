# Training Operations Studio + local Ollama (Windows / Docker)

## Start (no paid API key or card required)

1. Install Docker Desktop and start it. Ollama runs in a Docker container; a separate Windows Ollama installation is NOT required.
2. Copy `.env.example` to `.env` and set unique strong `SECRET_KEY` and `POSTGRES_PASSWORD`. Do not put real passwords in Git.
3. Run from this folder in PowerShell:

```powershell
Copy-Item .env.example .env
# Edit .env before starting

docker compose up -d --build db ollama web
# Download model once (several GB; needs Internet for initial download)
docker compose run --rm ollama-pull
# Verify model is available
docker compose exec ollama ollama list
# Open the website
Start-Process http://localhost:5001
```

The `ollama_data` volume persists the downloaded model. `app_data` and `postgres_data` persist uploads and DB records. Do not run `docker compose down -v` unless you intend to erase these volumes.

## Free local API endpoints

- Inside Docker (from web container): `http://ollama:11434/v1/chat/completions` (OpenAI compatible)
- Inside Docker native: `http://ollama:11434/api/chat`
- Inside Docker model list: `http://ollama:11434/api/tags`
- Inside Docker model download: `http://ollama:11434/api/pull`

The Ollama port is intentionally **not exposed to Windows or the internet**. You can test it with:

```powershell
docker compose exec ollama ollama list
docker compose exec web python -c "import urllib.request; print(urllib.request.urlopen('http://ollama:11434/api/tags').read().decode()[:1000])"
```

To test a chat completion without exposing port 11434:

```powershell
@'
import json, urllib.request
url = 'http://ollama:11434/v1/chat/completions'
body = json.dumps({'model':'llama3.2:3b','messages':[{'role':'user','content':'Reply with the word ready'}],'stream':False}).encode()
req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'})
print(json.load(urllib.request.urlopen(req, timeout=600))['choices'][0]['message']['content'])
'@ | docker compose exec -T web python -
```

Local Ollama does **not** require an API key or paid subscription. `AI_API_KEY=ollama` is a dummy compatibility value. Model downloads require internet initially; local inference then runs on your hardware and can be slow on CPU. For sensitive corporate videos, obtain approval and validate infrastructure security before use.

## Optional: Windows host API access

If you specifically need PowerShell to call `http://localhost:11434`, add under `ollama:` in `docker-compose.yml`:

```yaml
    ports:
      - "127.0.0.1:11434:11434"
```

Then `docker compose up -d ollama`. Do not bind to `0.0.0.0` or expose the unauthenticated Ollama API publicly.

## Tests

```powershell
# From project root with Python dependencies installed:
python -m unittest discover -s tests -v
```

The supplied Q1/Q2 tests mock AI and use an isolated test database; they do not substitute for sponsor validation or a real Ollama end-to-end test.

## Existing data

The Compose project name is `training-clips-studio` to reuse the existing Studio volumes if the previous deployment used that name. **Back up your volumes before switching.** If you previously used a different project name, check `docker volume ls` and migrate deliberately; do not assume the new project sees the old videos.

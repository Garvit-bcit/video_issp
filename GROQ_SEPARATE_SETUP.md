# Groq comparison copy (separate from Ollama)

This copy preserves the merged application's Python, UI, clip-generation, SOP and test files without changes.

## Run in a DIFFERENT folder from Ollama

1. Extract this ZIP separately. Open PowerShell in the extracted `training-operations-studio` directory.
2. Run `Copy-Item .env.example .env` and `notepad .env`.
3. Set `AI_API_KEY` to your Groq key from https://console.groq.com/keys . Set strong and DIFFERENT `POSTGRES_PASSWORD` and `SECRET_KEY` values.
4. Run `docker compose config --quiet` then `docker compose up -d --build web db`.
5. Open http://localhost:5002 . Ollama stays at http://localhost:5001 .

## Isolation

Compose project `training-clips-groq` has its own web image, containers, network, PostgreSQL data volume and video/report volume. No Ollama service is started. The Groq API uses `https://api.groq.com/openai/v1/chat/completions`.

## Compare

Upload the SAME non-sensitive test video to both sites, transcribe it, then generate an SOP and clips separately. Since databases are isolated, videos are not shared. Compare elapsed time and quality. Groq requires internet access and transmits transcript content to Groq; do not use sensitive company data without authorization.

## Useful commands

- `docker compose ps`
- `docker compose logs --tail 100 web`
- `docker compose up -d --build --no-deps web`
- `docker compose down` (without `-v`, to preserve volumes)

## Note

Only Compose configuration and `.env.example` were changed; application source files are identical to the merged Ollama copy. The Groq provider may enforce rate limits or reject JSON responses; test the actual API workflows before concluding the versions perform equivalently.

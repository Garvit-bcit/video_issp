# Training Operations Studio — separate installation

This edition runs at **http://localhost:5001**, separately from your existing application at port 5000. The Compose project is explicitly named `training-clips-studio`, with separate database and uploaded-video volumes. Existing accounts and videos are **not** automatically copied.

1. Extract this ZIP into a **different folder** from your original application.
2. Copy your own `.env` into this folder. Keep it private and set `POSTGRES_PASSWORD`, `SECRET_KEY`, and the Groq `AI_*` values. See `.env.example`.
3. In PowerShell, from the extracted project folder, run `docker compose up -d --build`.
4. Check `docker compose ps` and visit `http://localhost:5001`.
5. Create or bootstrap an admin account according to the README, then upload a **non-sensitive** video, transcribe it, and select **Create segments**.

Your original project at `http://localhost:5000` is unaffected provided you launch this project from its separate folder and do not override the Compose project name.

Do not add a payment card to test Groq. Free-tier usage is subject to limits. For company-sensitive videos, obtain authorization before submitting transcripts to an external AI service.

Changes to `app.py` during development can be copied into the running container with `docker compose cp app.py web:/app/app.py` followed by `docker compose restart web`; changes to the Dockerfile or dependencies require a rebuild.

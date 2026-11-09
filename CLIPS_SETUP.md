# Automatic short training clips — setup

## What changed
- `clips_feature.py`: AI lesson planning, FFmpeg clip generation, owner-checked clip API.
- `app.py`: registers clip routes and removes clips on video deletion.
- `templates/index.html` and `static/app.js`: generate, play and download lessons.

## Setup on Windows PowerShell
1. Back up your existing project and Docker volumes. Extract this ZIP to a **new folder**.
2. Copy your existing `.env` into the extracted `video-training-starter` folder; the ZIP intentionally excludes secrets. Do not commit `.env`.
3. Verify `AI_PROVIDER=openai_compatible`, `AI_BASE_URL=https://api.groq.com/openai/v1`, `AI_MODEL=openai/gpt-oss-20b`, and your own `AI_API_KEY`. Preserve your `POSTGRES_PASSWORD` and `SECRET_KEY`.
4. In PowerShell, `cd` to the extracted `video-training-starter` folder.
5. Run `docker compose up -d --build` to launch a **separate new project**. IMPORTANT: This edition sets the Compose project name to `training-clips-studio`, so its PostgreSQL database and uploads are separate from your original application. It does not automatically import your old videos or accounts.
6. Open http://localhost:5001, log in, open a non-sensitive video, click Transcribe if needed, then Generate clips.
7. Clips appear below the video and can be played/downloaded individually.

## Faster development after initial build
If you copied the files into your original project and only edit Python/JS/templates: `docker compose cp app.py web:/app/app.py`; `docker compose cp clips_feature.py web:/app/clips_feature.py`; `docker compose cp static/app.js web:/app/static/app.js`; `docker compose cp templates/index.html web:/app/templates/index.html`; `docker compose restart web`. These manual copies are temporary until a rebuild.

## API endpoints (authenticated)
- GET `/api/videos/<video_id>/clips` — list generated clips
- POST `/api/videos/<video_id>/clips/generate` — generate/replace clips
- GET `/api/videos/<video_id>/clips/<index>/file` — stream/download an MP4

## Limitations
- This first version generates clips synchronously; large videos can take minutes.
- Requires an existing timestamped transcript and Groq access.
- AI-suggested clip boundaries may not be exact; review each clip.
- Test only with non-sensitive video unless your organization authorizes third-party AI processing.
- Do not delete Docker volumes when upgrading; they contain your application data.

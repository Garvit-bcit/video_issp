# Training Video Workspace

A Flask application for turning training recordings into timestamped transcripts, editable instructions, and reviewable Standard Operating Procedure (SOP) PDFs. The existing SQLite starter schema and video/step records are preserved; the app adds authentication, user ownership, report records, and PostgreSQL support.

## What changed

- **Workspace UI:** persistent video player beside an independently scrollable transcript/instruction panel on desktop; responsive stacked layout on smaller screens; timestamp seeking, status pills, loading/error messages, video library and editing.
- **Authentication:** sign-in/out, hashed passwords, session cookies, admin-only account management, enabled/disabled accounts, roles, backend ownership checks and non-disclosing 404s for resources outside a user's workspace. Public registration is intentionally disabled.
- **AI SOP generation:** configurable OpenAI-compatible Chat Completions endpoint, JSON-structured SOP drafting, editable preview, saved reports, and PDF export. The service refuses to claim success when AI isn't configured.
- **PDFs:** professional SOP headings, prerequisite and warning sections, timestamped steps, review flags, footer and page numbers.
- **Deployment:** Dockerfile and Compose with PostgreSQL, private database network, persistent database/media volumes, environment configuration and FFmpeg.
- **Migration safety:** startup adds missing legacy SQLite columns without dropping existing records. Old records are assigned to the first admin when that admin is created.

## Local development on Windows

1. Install Python 3.11/3.12 and FFmpeg (both `ffmpeg` and `ffprobe` must work in PowerShell).
2. Create and activate an environment:

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.example .env
   ```
3. Edit `.env`: set `SECRET_KEY` to a long random value. Keep the existing `.env` safe; do not commit it.
4. Run `python app.py`, then visit `http://127.0.0.1:5000`.
5. Create the initial administrator securely:

   ```powershell
   python scripts_create_admin.py
   ```

   The password is entered interactively and is not echoed or placed in shell history. Sign in and use **Admin Panel** to create normal users.

6. Optional transcription: `pip install faster-whisper`. FFmpeg is also required; the first Whisper run downloads the selected model and can be slow on CPU.

## Docker Compose

1. Install Docker Desktop and start it.
2. Copy `.env.example` to `.env`, set unique long random values for `SECRET_KEY` and `POSTGRES_PASSWORD`, and keep `AI_API_KEY` blank until needed.
3. Build and start:

   ```powershell
   docker compose up --build -d
   docker compose logs -f web
   ```
4. Create the first admin account interactively inside the running container:

   ```powershell
   docker compose exec web python scripts_create_admin.py
   ```
5. Visit `http://127.0.0.1:5000`. Compose binds the web service to loopback only. The database has no host-published port. Volumes `postgres_data` and `app_data` persist PostgreSQL records, uploaded videos and reports across restarts.
6. Stop without deleting data: `docker compose down`. **Do not use `docker compose down -v` unless you intentionally want to delete persistent volumes.**

For production behind a reverse proxy, enable HTTPS and set `COOKIE_SECURE=true`; configure the proxy, backups, monitoring, and request limits appropriately. Do not expose the app publicly before a security review.

## AI provider setup

The current adapter uses an OpenAI-compatible `/chat/completions` endpoint and keeps provider calls isolated in `generate_sop()` in `app.py`. Configure in `.env`:

```dotenv
AI_PROVIDER=openai_compatible
AI_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your-secret-key
AI_MODEL=your-supported-model-name
AI_TIMEOUT_SECONDS=120
```

Use the API provider's exact supported model identifier. Never commit `.env` or share secrets. For compatible providers, set `AI_BASE_URL` to the provider's API base. When any required value is missing, transcript editing and PDF export continue to work and the UI clearly reports that AI report generation is not configured. The model is instructed to preserve order and timestamps and flag uncertainty, but a human must verify every generated procedure.

## Database and legacy data

### Existing SQLite project

Back up the complete `instance/` directory (database and videos) before upgrading. Startup runs additive migrations for the legacy `videos.user_id` and `steps.kind` columns; it does not drop rows. Create an admin using `python scripts_create_admin.py`; the script assigns legacy ownerless videos to that admin. Once assigned, the videos remain private to that admin unless an administrator deliberately reassigns ownership.

### Moving SQLite data to PostgreSQL

Do not point the new PostgreSQL app at the old SQLite file or delete the original. Keep a verified copy of the SQLite database and `instance/videos/`. For a production migration, take the application offline, create the target database, create an admin on the target, then export/import `videos` and `steps` while mapping old records to that admin's user ID. Copy media files to the target `VIDEO_STORAGE`, preserve video IDs and filenames, and validate row counts, playback and PDF output before switching users over. The old SQLite directory should remain as a rollback copy until validation is complete. This starter intentionally does not perform a silent automatic SQLite-to-PostgreSQL data copy.

`migrations/versions/001_add_ownership_and_reports.sql` documents the additive legacy schema changes. New tables are created by SQLAlchemy at startup. Back up before applying migrations to any non-disposable database.

## Navigation

- **Dashboard / My Videos:** upload, transcribe, edit timestamped instructions, seek video and export a draft PDF.
- **AI Report Generation:** generate, preview and edit the SOP, save changes and download a report PDF.
- **Generated Documents:** list saved reports and download PDFs.
- **About:** application purpose and workflow.
- **Admin Panel:** create accounts, set roles, enable/disable accounts, reset passwords and delete accounts.

## Tests and current limitations

Run basic checks:

```powershell
python -m py_compile app.py scripts_create_admin.py
python -m unittest discover -s tests -v
```

AI API access and Whisper are external/configurable dependencies. Transcription currently runs in a background thread and may be interrupted by a process restart; on restart it is marked failed and can be retried. Use one web worker for this starter deployment. The AI adapter currently targets OpenAI-compatible chat-completions APIs; a provider with a different interface needs an adapter change. AI output must be reviewed before use as an operational SOP. Admins can view all videos; normal users are restricted to their own resources by backend checks. Public signup is intentionally omitted; admins create accounts.

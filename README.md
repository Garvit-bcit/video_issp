# Training Video Workspace — Local Starter

A **local-only prototype** for uploading training recordings, creating timestamped transcript sections with optional `faster-whisper`, editing them into instructions, jumping to video timestamps, and exporting instructions as PDF.

**Not included yet:** automatic AI instruction writing, baseline research report, screenshot understanding, Clipchamp automation, Stream/Graph integration, accounts/roles, cloud deployment, or sponsor-ready security. This is not a clone of Microsoft tools.

## Windows quick start (PowerShell)

1. Install Python 3.11 or 3.12 and FFmpeg. Ensure `python`, `ffmpeg`, and `ffprobe` work in PowerShell.
2. Open PowerShell in this folder.
3. Run:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

4. Paste the generated random string into `.env` as `SECRET_KEY`.
5. Optional: `pip install faster-whisper` (needed for Transcribe button). The first run downloads a model and can take time on CPU.
6. Run `python app.py` and visit `http://127.0.0.1:5000`.
7. Upload a short, non-confidential MP4 with spoken audio. Test clicking timestamps and downloading the PDF.

## How it works

- `app.py`: Flask routes, SQLite, upload, optional Whisper job, PDF generation.
- `templates/index.html`: website layout.
- `static/app.js`: upload, player seeking, step editing.
- `static/style.css`: styles.
- `instance/`: generated SQLite database and uploaded videos. **Never commit or share sponsor videos**.

## Important limitations

- **No login or team permissions**. Run on localhost only, not a public server.
- Transcription is local and may be slow; it creates *transcript sections*, **not verified training instructions**. Review and rewrite them.
- Transcription jobs run in background threads and are interrupted if the app restarts.
- The PDF contains editable step text but not linked Stream videos or screenshots.
- File-size checks, upload validation, and browser playback are basic prototype functionality, not production hardening.
- Transcribing again replaces auto-generated sections titled `Transcript section ...`; rename reviewed sections before rerunning if you want to keep them.
- The app stores all data on the local machine. Back up the `instance/` folder securely if needed.

## Handover

See `Project_Handover_and_Next_Steps.docx` for installation, architecture, demo script, future integrations, security tasks, and a reusable prompt for continuing development after uploading this code to ChatGPT.

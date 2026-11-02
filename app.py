"""Local-first training-video documentation starter. No Microsoft/API credentials required."""
import io
import os
import sqlite3
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from flask import Flask, abort, jsonify, render_template, request, send_file
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
from reportlab.lib.utils import simpleSplit
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
DATA = ROOT / 'instance'
VIDEOS = DATA / 'videos'
VIDEOS.mkdir(parents=True, exist_ok=True)
DB = DATA / 'training.db'
app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_UPLOAD_MB', '500')) * 1024 * 1024
app.secret_key = os.getenv('SECRET_KEY', 'development-only-change-this')
lock = threading.Lock()


def conn():
    db = sqlite3.connect(DB, timeout=30)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    with conn() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
            duration REAL DEFAULT 0, status TEXT NOT NULL DEFAULT 'uploaded',
            error TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT NOT NULL,
            position INTEGER NOT NULL, start_sec REAL NOT NULL DEFAULT 0,
            end_sec REAL NOT NULL DEFAULT 0, title TEXT NOT NULL, body TEXT NOT NULL,
            FOREIGN KEY(video_id) REFERENCES videos(id)
        );
        ''')
        # An interrupted job is retryable after restarting the server.
        db.execute("UPDATE videos SET status='failed', error='Server restarted; please retry.' WHERE status='transcribing'")

initialize()


def fetch_video(video_id):
    with conn() as db:
        video = db.execute('SELECT * FROM videos WHERE id=?', (video_id,)).fetchone()
    if video is None:
        abort(404)
    return dict(video)


def fetch_steps(video_id):
    with conn() as db:
        rows = db.execute('SELECT * FROM steps WHERE video_id=? ORDER BY position, id', (video_id,)).fetchall()
    return [dict(x) for x in rows]


def ffprobe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                             '-of', 'default=noprint_wrappers=1:nokey=1', str(path)],
                            capture_output=True, text=True, timeout=45)
    if result.returncode != 0:
        raise ValueError('Invalid video or FFmpeg/ffprobe is missing.')
    return float(result.stdout.strip() or 0)


@app.get('/')
def home():
    return render_template('index.html')


@app.get('/api/videos')
def list_videos():
    with conn() as db:
        rows = db.execute('SELECT * FROM videos ORDER BY created_at DESC').fetchall()
    return jsonify([dict(row) for row in rows])


@app.post('/api/videos')
def upload():
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify(error='Select a video.'), 400
    ext = Path(file.filename).suffix.lower()
    if ext not in {'.mp4', '.mov', '.webm'}:
        return jsonify(error='Upload MP4, MOV, or WebM.'), 400
    video_id = uuid.uuid4().hex
    filename = video_id + ext
    path = VIDEOS / filename
    file.save(path)
    try:
        duration = ffprobe(path)
    except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
        path.unlink(missing_ok=True)
        return jsonify(error=str(exc)), 400
    title = (request.form.get('title') or Path(file.filename).stem).strip()[:150] or 'Untitled video'
    with conn() as db:
        db.execute('INSERT INTO videos(id,title,filename,duration) VALUES(?,?,?,?)',
                   (video_id, title, filename, duration))
    return jsonify(id=video_id), 201


@app.delete('/api/videos/<video_id>')
def delete_video(video_id):
    # Do not remove a video while its background transcription is using it.
    video = fetch_video(video_id)
    if video['status'] == 'transcribing':
        return jsonify(error='Wait for transcription to finish before deleting this video.'), 409

    video_path = (VIDEOS / video['filename']).resolve()
    videos_dir = VIDEOS.resolve()
    if video_path.parent != videos_dir:
        return jsonify(error='Invalid video file path.'), 400

    # Remove the video and all its saved instructions in one database transaction.
    with conn() as db:
        db.execute('DELETE FROM steps WHERE video_id=?', (video_id,))
        db.execute('DELETE FROM videos WHERE id=?', (video_id,))

    # The database entry is removed first; missing files are okay.
    video_path.unlink(missing_ok=True)
    return '', 204


@app.get('/api/videos/<video_id>')
def details(video_id):
    v = fetch_video(video_id)
    v['steps'] = fetch_steps(video_id)
    return jsonify(v)


@app.get('/api/videos/<video_id>/file')
def video_file(video_id):
    v = fetch_video(video_id)
    return send_file(VIDEOS / v['filename'], conditional=True)


@app.post('/api/videos/<video_id>/steps')
def add_step(video_id):
    v = fetch_video(video_id)
    data = request.get_json(silent=True) or {}
    try:
        start = float(data.get('start_sec', 0))
        end = float(data.get('end_sec', start))
    except (ValueError, TypeError):
        return jsonify(error='Timestamps must be numbers.'), 400
    if start < 0 or end < start or start > v['duration'] + 1:
        return jsonify(error='Invalid timestamps.'), 400
    title = str(data.get('title', '')).strip()[:150]
    body = str(data.get('body', '')).strip()[:4000]
    if not title or not body:
        return jsonify(error='Title and instructions are required.'), 400
    with conn() as db:
        pos = db.execute('SELECT COALESCE(MAX(position),0)+1 FROM steps WHERE video_id=?', (video_id,)).fetchone()[0]
        cur = db.execute('INSERT INTO steps(video_id,position,start_sec,end_sec,title,body) VALUES(?,?,?,?,?,?)',
                         (video_id, pos, start, end, title, body))
    return jsonify(id=cur.lastrowid), 201


@app.put('/api/steps/<int:step_id>')
def update_step(step_id):
    data = request.get_json(silent=True) or {}
    with conn() as db:
        old = db.execute('SELECT * FROM steps WHERE id=?', (step_id,)).fetchone()
        if not old:
            abort(404)
        video = fetch_video(old['video_id'])
        try:
            start = float(data.get('start_sec', old['start_sec']))
            end = float(data.get('end_sec', old['end_sec']))
        except (ValueError, TypeError):
            return jsonify(error='Invalid timestamp.'), 400
        title = str(data.get('title', old['title'])).strip()[:150]
        body = str(data.get('body', old['body'])).strip()[:4000]
        if start < 0 or end < start or start > video['duration'] + 1 or not title or not body:
            return jsonify(error='Invalid step details.'), 400
        db.execute('UPDATE steps SET start_sec=?,end_sec=?,title=?,body=? WHERE id=?',
                   (start, end, title, body, step_id))
    return jsonify(ok=True)


@app.delete('/api/steps/<int:step_id>')
def delete_step(step_id):
    with conn() as db:
        db.execute('DELETE FROM steps WHERE id=?', (step_id,))
    return '', 204


def run_transcription(video_id):
    try:
        from faster_whisper import WhisperModel
        v = fetch_video(video_id)
        with tempfile.TemporaryDirectory() as tmp:
            audio = Path(tmp) / 'audio.wav'
            result = subprocess.run(['ffmpeg', '-y', '-i', str(VIDEOS / v['filename']),
                                     '-vn', '-ac', '1', '-ar', '16000', str(audio)],
                                    capture_output=True, timeout=1800)
            if result.returncode != 0:
                raise RuntimeError('Could not extract audio; check video audio track.')
            model = WhisperModel(os.getenv('WHISPER_MODEL', 'base'), device='cpu', compute_type='int8')
            segments, _ = model.transcribe(str(audio), vad_filter=True)
            generated = [(video_id, i + 1, float(s.start), float(s.end),
                          f'Transcript section {i + 1}', s.text.strip())
                         for i, s in enumerate(segments) if s.text.strip()]
        with conn() as db:
            # Transcription only replaces previous auto-generated transcript sections.
            db.execute("DELETE FROM steps WHERE video_id=? AND title LIKE 'Transcript section %'", (video_id,))
            db.executemany('INSERT INTO steps(video_id,position,start_sec,end_sec,title,body) VALUES(?,?,?,?,?,?)', generated)
            db.execute("UPDATE videos SET status='ready',error='' WHERE id=?", (video_id,))
    except Exception as exc:
        with conn() as db:
            db.execute('UPDATE videos SET status=?,error=? WHERE id=?', ('failed', str(exc)[:300], video_id))


@app.post('/api/videos/<video_id>/transcribe')
def transcribe(video_id):
    v = fetch_video(video_id)
    if v['status'] == 'transcribing':
        return jsonify(error='Transcription is already running.'), 409
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return jsonify(error='Install local Whisper first: pip install faster-whisper'), 400
    with conn() as db:
        db.execute("UPDATE videos SET status='transcribing',error='' WHERE id=?", (video_id,))
    threading.Thread(target=run_transcription, args=(video_id,), daemon=True).start()
    return jsonify(status='transcribing'), 202


@app.get('/api/videos/<video_id>/pdf')
def export_pdf(video_id):
    video = fetch_video(video_id)
    steps = fetch_steps(video_id)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=(595, 842), rightMargin=52, leftMargin=52)
    styles = getSampleStyleSheet()
    story = [Paragraph(escape(video['title']), styles['Title']),
             Paragraph('Training Instructions | Draft for Human Review', styles['Normal']), Spacer(1, 20)]
    for index, step in enumerate(steps, 1):
        mins, secs = divmod(int(step['start_sec']), 60)
        story.append(KeepTogether([
            Paragraph(f"{index}. {escape(step['title'])} ({mins:02}:{secs:02})", styles['Heading2']),
            Paragraph(escape(step['body']).replace('\n', '<br/>'), styles['BodyText']), Spacer(1, 12)
        ]))
    if not steps:
        story.append(Paragraph('No instructions have been added yet.', styles['BodyText']))
    doc.build(story)
    buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=True,
                     download_name='training-instructions.pdf')


@app.errorhandler(413)
def too_large(_):
    return jsonify(error='Video exceeds configured upload limit.'), 413


if __name__ == '__main__':
    app.run(debug=True, port=5000)

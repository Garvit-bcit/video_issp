"""Training Video Workspace Flask application.

Routes, database models, authentication, video processing, and SOP exports.
"""

import io, json, os, re, secrets, sqlite3, subprocess, tempfile, threading, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from functools import wraps
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for, flash
from flask_login import LoginManager, UserMixin, current_user, login_required, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
from xml.sax.saxutils import escape
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env', override=False)
DATA = Path(os.getenv('DATA_DIR', str(ROOT / 'instance'))).resolve()
VIDEOS = Path(os.getenv('VIDEO_STORAGE', str(DATA / 'videos'))).resolve()
REPORTS = Path(os.getenv('REPORT_STORAGE', str(DATA / 'reports'))).resolve()
for p in (DATA, VIDEOS, REPORTS):
    p.mkdir(parents=True, exist_ok=True)
app = Flask(__name__)
app.config["SESSION_COOKIE_NAME"] = "groq_session"
if os.getenv('DEPLOYMENT_MODE', '').lower() == 'production' and (len(os.getenv('SECRET_KEY', '')) < 32 or 'replace-with' in os.getenv('SECRET_KEY', '').lower()):
    raise RuntimeError('Production requires SECRET_KEY with at least 32 characters.')
uri = os.getenv('DATABASE_URL', 'sqlite:///' + str(DATA / 'training.db')).replace('postgres://', 'postgresql://', 1)
app.config.update(SECRET_KEY=os.getenv('SECRET_KEY') or 'dev-only-change-this', SQLALCHEMY_DATABASE_URI=uri, SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=int(os.getenv('MAX_UPLOAD_MB', '500')) * 1024 * 1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE', 'false').lower() == 'true')
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, p):
        self.password_hash = generate_password_hash(p)

    def check_password(self, p):
        return check_password_hash(self.password_hash, p)

class Video(db.Model):
    __tablename__ = 'videos'
    id = db.Column(db.String(32), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    title = db.Column(db.String(150), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    duration = db.Column(db.Float, default=0)
    status = db.Column(db.String(30), default='uploaded', nullable=False)
    error = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    steps = db.relationship('Step', backref='video', cascade='all, delete-orphan', order_by='Step.position')
    reports = db.relationship('Report', backref='video', cascade='all, delete-orphan')

class Step(db.Model):
    __tablename__ = 'steps'
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.String(32), db.ForeignKey('videos.id', ondelete='CASCADE'), nullable=False, index=True)
    position = db.Column(db.Integer, nullable=False, default=1)
    start_sec = db.Column(db.Float, nullable=False, default=0)
    end_sec = db.Column(db.Float, nullable=False, default=0)
    title = db.Column(db.String(150), nullable=False)
    body = db.Column(db.Text, nullable=False)
    kind = db.Column(db.String(30), default='instruction')

class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    video_id = db.Column(db.String(32), db.ForeignKey('videos.id', ondelete='CASCADE'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    content_json = db.Column(db.Text, nullable=False)
    source = db.Column(db.String(30), default='manual')
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

@login_manager.user_loader
def load_user(uid):
    try:
        return db.session.get(User, int(uid))
    except (ValueError, TypeError):
        return None

def admin_required(fn):

    @wraps(fn)
    @login_required
    def wrapped(*a, **kw):
        if current_user.role != 'admin':
            abort(403)
        return fn(*a, **kw)
    return wrapped

def owner_video(vid):
    v = db.session.get(Video, vid)
    if not v or (v.user_id != current_user.id and current_user.role != 'admin'):
        abort(404)
    return v

def owner_step(sid):
    s = db.session.get(Step, sid)
    if not s:
        abort(404)
    owner_video(s.video_id)
    return s

def init_db():
    with app.app_context():
        db.create_all()
        if db.engine.dialect.name == 'sqlite':
            con = sqlite3.connect(db.engine.url.database)
            try:
                tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if 'videos' in tables:
                    cols = {r[1] for r in con.execute('PRAGMA table_info(videos)')}
                    if 'user_id' not in cols:
                        con.execute('ALTER TABLE videos ADD COLUMN user_id INTEGER')
                if 'steps' in tables:
                    cols = {r[1] for r in con.execute('PRAGMA table_info(steps)')}
                    if 'kind' not in cols:
                        con.execute("ALTER TABLE steps ADD COLUMN kind VARCHAR(30) DEFAULT 'instruction'")
                    con.execute("UPDATE steps SET kind='transcript' WHERE title LIKE 'Transcript section %' AND (kind IS NULL OR kind='instruction')")
                con.commit()
            finally:
                con.close()
        username = os.getenv('BOOTSTRAP_ADMIN_USERNAME', '').strip()
        password = os.getenv('BOOTSTRAP_ADMIN_PASSWORD', '')
        if username and password and (not User.query.filter_by(username=username).first()):
            u = User(username=username, role='admin')
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
        admin = User.query.filter_by(role='admin').order_by(User.id).first()
        if admin:
            Video.query.filter(Video.user_id.is_(None)).update({Video.user_id: admin.id}, synchronize_session=False)
            db.session.commit()
        Video.query.filter_by(status='transcribing').update({Video.status: 'failed', Video.error: 'Server restarted; please retry.'})
        db.session.commit()
init_db()

from clips_feature import install_clips
install_clips(app, owner_video, VIDEOS)

def stamp(sec):
    n = max(0, int(float(sec or 0)))
    return f'{n // 60:02}:{n % 60:02}'

def serialize_step(s):
    return {k: getattr(s, k) for k in ('id', 'video_id', 'position', 'start_sec', 'end_sec', 'title', 'body', 'kind')}

def serialize_video(v, steps=False):
    d = {'id': v.id, 'title': v.title, 'filename': v.filename, 'duration': v.duration or 0, 'status': v.status, 'error': v.error or '', 'created_at': v.created_at.isoformat() if v.created_at else ''}
    if steps:
        d['steps'] = [serialize_step(s) for s in v.steps]
    return d

def ffprobe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(path)], capture_output=True, text=True, timeout=45)
    if r.returncode:
        raise ValueError('Invalid video or FFmpeg/ffprobe is missing.')
    return float(r.stdout.strip() or 0)

@app.context_processor
def ctx():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_urlsafe(32)
    return {'is_admin': current_user.is_authenticated and current_user.role == 'admin', 'csrf_token': session['_csrf_token']}

@app.before_request
def reject_disabled_account():
    if current_user.is_authenticated and (not current_user.enabled):
        logout_user()
        session.clear()
        if request.endpoint not in ('login', 'login_post', 'static'):
            return redirect(url_for('login'))

@app.before_request
def csrf_protect():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
        supplied = request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token', '')
        if not supplied or not secrets.compare_digest(supplied, session.get('_csrf_token', '')):
            return (jsonify(error='Security token missing or expired. Refresh the page and try again.'), 400)

@app.get('/login')
def login():
    return redirect(url_for('home')) if current_user.is_authenticated else render_template('login.html')

@app.post('/login')
def login_post():
    u = User.query.filter_by(username=request.form.get('username', '').strip()).first()
    if not u or not u.enabled or (not u.check_password(request.form.get('password', ''))):
        flash('Incorrect credentials or this account is disabled.', 'error')
        return redirect(url_for('login'))
    login_user(u)
    session.permanent = True
    app.permanent_session_lifetime = timedelta(hours=int(os.getenv('SESSION_HOURS', '8')))
    return redirect(url_for('home'))

@app.post('/logout')
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('login'))

@app.get('/')
@login_required
def home():
    return render_template('index.html')

@app.get('/about')
@login_required
def about():
    return render_template('about.html')

@app.get('/admin')
@admin_required
def admin_page():
    return render_template('admin.html', users=User.query.order_by(User.created_at.desc()).all())

@app.post('/admin/users')
@admin_required
def create_user():
    name = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'user')
    if len(name) < 3 or len(password) < 12 or role not in ('user', 'admin'):
        flash('Username must be 3+ characters; password must be 12+ characters.', 'error')
    elif User.query.filter_by(username=name).first():
        flash('Username already exists.', 'error')
    else:
        u = User(username=name, role=role)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        flash('User created.', 'success')
    return redirect(url_for('admin_page'))

@app.post('/admin/users/<int:uid>/update')
@admin_required
def update_user(uid):
    u = db.session.get(User, uid)
    if not u:
        abort(404)
    enabled = request.form.get('enabled') == '1'
    if u.id == current_user.id and (not enabled):
        flash('You cannot disable your own account.', 'error')
    else:
        pw = request.form.get('password', '')
        if pw and len(pw) < 12:
            flash('Password must contain at least 12 characters.', 'error')
            return redirect(url_for('admin_page'))
        u.enabled = enabled
        role = request.form.get('role', u.role)
        if role in ('user', 'admin'):
            u.role = role
        if pw:
            u.set_password(pw)
        db.session.commit()
        flash('Account updated.', 'success')
    return redirect(url_for('admin_page'))

def remove_files(v):
    import shutil
    shutil.rmtree(VIDEOS / 'clips' / v.id, ignore_errors=True)
    path = (VIDEOS / v.filename).resolve()
    if path.parent == VIDEOS.resolve():
        path.unlink(missing_ok=True)
    for r in v.reports:
        path = (REPORTS / f'report-{r.id}.pdf').resolve()
        if path.parent == REPORTS.resolve():
            path.unlink(missing_ok=True)

@app.post('/admin/users/<int:uid>/delete')
@admin_required
def delete_user(uid):
    u = db.session.get(User, uid)
    if not u:
        abort(404)
    if u.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
    else:
        for v in Video.query.filter_by(user_id=u.id).all():
            remove_files(v)
            db.session.delete(v)
        db.session.delete(u)
        db.session.commit()
        flash('User and workspace data deleted.', 'success')
    return redirect(url_for('admin_page'))

@app.get('/api/videos')
@login_required
def list_videos():
    q = Video.query if current_user.role == 'admin' else Video.query.filter_by(user_id=current_user.id)
    return jsonify([serialize_video(v) for v in q.order_by(Video.created_at.desc()).all()])

@app.post('/api/videos')
@login_required
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return (jsonify(error='Choose a video file.'), 400)
    ext = Path(secure_filename(f.filename)).suffix.lower()
    if ext not in ('.mp4', '.mov', '.webm'):
        return (jsonify(error='Supported formats: MP4, MOV, and WebM.'), 400)
    vid = uuid.uuid4().hex
    filename = vid + ext
    path = VIDEOS / filename
    f.save(path)
    try:
        duration = ffprobe(path)
    except (ValueError, OSError, subprocess.TimeoutExpired) as e:
        path.unlink(missing_ok=True)
        return (jsonify(error=str(e)), 400)
    v = Video(id=vid, user_id=current_user.id, title=(request.form.get('title') or Path(f.filename).stem).strip()[:150] or 'Untitled video', filename=filename, duration=duration, status='uploaded')
    db.session.add(v)
    db.session.commit()
    return (jsonify(id=vid), 201)

@app.delete('/api/videos/<vid>')
@login_required
def delete_video(vid):
    v = owner_video(vid)
    if v.status == 'transcribing':
        return (jsonify(error='Wait for transcription to finish before deleting it.'), 409)
    remove_files(v)
    db.session.delete(v)
    db.session.commit()
    return ('', 204)

@app.get('/api/videos/<vid>')
@login_required
def details(vid):
    return jsonify(serialize_video(owner_video(vid), True))

@app.get('/api/videos/<vid>/file')
@login_required
def video_file(vid):
    v = owner_video(vid)
    p = (VIDEOS / v.filename).resolve()
    if p.parent != VIDEOS.resolve() or not p.is_file():
        abort(404)
    return send_file(p, conditional=True)

@app.post('/api/videos/<vid>/steps')
@login_required
def add_step(vid):
    v = owner_video(vid)
    d = request.get_json(silent=True) or {}
    try:
        start = float(d.get('start_sec', 0))
        end = float(d.get('end_sec', start))
    except (TypeError, ValueError):
        return (jsonify(error='Timestamps must be numbers.'), 400)
    title = str(d.get('title', '')).strip()[:150]
    body = str(d.get('body', '')).strip()[:4000]
    if start < 0 or end < start or start > v.duration + 1 or (not title) or (not body):
        return (jsonify(error='Enter a title, instructions, and valid timestamps.'), 400)
    s = Step(video_id=vid, position=max([x.position for x in v.steps] or [0]) + 1, start_sec=start, end_sec=end, title=title, body=body, kind='instruction')
    db.session.add(s)
    db.session.commit()
    return (jsonify(id=s.id), 201)

@app.put('/api/steps/<int:sid>')
@login_required
def update_step(sid):
    s = owner_step(sid)
    d = request.get_json(silent=True) or {}
    try:
        start = float(d.get('start_sec', s.start_sec))
        end = float(d.get('end_sec', s.end_sec))
    except (TypeError, ValueError):
        return (jsonify(error='Timestamps must be numbers.'), 400)
    title = str(d.get('title', s.title)).strip()[:150]
    body = str(d.get('body', s.body)).strip()[:4000]
    if start < 0 or end < start or start > s.video.duration + 1 or (not title) or (not body):
        return (jsonify(error='Invalid step details.'), 400)
    s.start_sec = start
    s.end_sec = end
    s.title = title
    s.body = body
    s.kind = 'instruction'
    db.session.commit()
    return jsonify(ok=True)

@app.delete('/api/steps/<int:sid>')
@login_required
def delete_step(sid):
    db.session.delete(owner_step(sid))
    db.session.commit()
    return ('', 204)

def transcribe_job(vid):
    try:
        from faster_whisper import WhisperModel
        with app.app_context():
            v = db.session.get(Video, vid)
            if not v:
                return
            with tempfile.TemporaryDirectory() as tmp:
                audio = Path(tmp) / 'audio.wav'
                r = subprocess.run(['ffmpeg', '-y', '-i', str(VIDEOS / v.filename), '-vn', '-ac', '1', '-ar', '16000', str(audio)], capture_output=True, timeout=1800)
                if r.returncode:
                    raise RuntimeError('Could not extract audio. Check the video audio track and FFmpeg installation.')
                model = WhisperModel(os.getenv('WHISPER_MODEL', 'base'), device=os.getenv('WHISPER_DEVICE', 'cpu'), compute_type=os.getenv('WHISPER_COMPUTE_TYPE', 'int8'))
                segments, _ = model.transcribe(str(audio), vad_filter=True)
                rows = [(float(s.start), float(s.end), s.text.strip()) for s in segments if s.text.strip()]
            Step.query.filter_by(video_id=vid, kind='transcript').delete()
            for i, (start, end, text) in enumerate(rows, 1):
                db.session.add(Step(video_id=vid, position=i, start_sec=start, end_sec=end, title=f'Transcript section {i}', body=text, kind='transcript'))
            v = db.session.get(Video, vid)
            v.status = 'ready'
            v.error = ''
            db.session.commit()
    except Exception as e:
        with app.app_context():
            v = db.session.get(Video, vid)
            if v:
                v.status = 'failed'
                v.error = str(e)[:500]
                db.session.commit()

@app.post('/api/videos/<vid>/transcribe')
@login_required
def transcribe(vid):
    v = owner_video(vid)
    if v.status == 'transcribing':
        return (jsonify(error='Transcription is already running.'), 409)
    try:
        import faster_whisper
    except ImportError:
        return (jsonify(error='Install faster-whisper to enable local transcription.'), 400)
    v.status = 'transcribing'
    v.error = ''
    db.session.commit()
    threading.Thread(target=transcribe_job, args=(vid,), daemon=True).start()
    return (jsonify(status='transcribing'), 202)

def ai_configured():
    return bool(os.getenv('AI_API_KEY') and os.getenv('AI_MODEL') and (os.getenv('AI_PROVIDER', 'openai_compatible').lower() in ('openai', 'openai_compatible')))

SOP_SYSTEM_PROMPT = """You write a work instruction that a new employee can follow on their first day, from part of a timestamped training-video transcript. The speaker talks casually; you turn that into clear, friendly instructions.
Return only JSON: {"document_title": "...", "overview": "...", "steps": [{"timestamp": "MM:SS", "title": "...", "detail": "...", "value": "...", "verify": "..."}]}

Rules:
- Write about {target} steps for this part. Each step is one meaningful task; merge small clicks and filler talk into it.
- title: a short instruction naming the task and object, with counts if spoken (e.g. "Measure the outside diameter (OD) on 25 pieces").
- detail: one or two plain sentences telling a new employee HOW to do it and linking it to the step before, e.g. "Once the drawing is checked, place each part in the gauge, take the reading and press the foot pedal to record it." Use "you", not "I". No filler words.
- timestamp: when the step starts, copied from the transcript.
- value: numbers, ranges or specifications spoken for the step (e.g. "410-426", "73, 75, 73, 70"). Empty string if none.
- verify: ONLY a real doubt a reviewer must check (a word that may be misheard, numbers that disagree, an unclear quantity or method). Empty string if none. Never write "correct", "done" or "X not found".
- overview (first part only): two sentences on what the procedure achieves and what equipment is used.
- Never invent steps, tools or numbers that are not in the transcript.

Example output (format only - it is about a DIFFERENT task; never copy its words, tools or numbers):
{"document_title": "Replace a Printer Toner Cartridge", "overview": "This procedure replaces the toner cartridge in the office printer and confirms print quality. You will need a new cartridge and the printer's front panel.",
 "steps": [
  {"timestamp": "00:12", "title": "Open the front cover and remove the old cartridge", "detail": "Switch the printer to standby first, then pull the front cover down and slide the old cartridge straight out.", "value": "", "verify": ""},
  {"timestamp": "01:05", "title": "Install the new cartridge", "detail": "Once the old cartridge is out, shake the new one gently, remove the seal and push it in until it clicks.", "value": "Model TN-2420", "verify": "Model number partly inaudible; confirm on the box"},
  {"timestamp": "02:40", "title": "Print a test page", "detail": "When the cover is closed, open the menu, choose Print Test Page and check that the page is even.", "value": "", "verify": ""}]}"""

# Notes a small model writes that tell the reviewer nothing ("That's correct", "PDF not saved").
_JUNK_VERIFY = re.compile(r"that'?s correct|^correct|^done|^n/?a$|^none$|\b(not|no) (found|saved|created|selected|entered|"
                          r"confirmed|minimized|attached|confirmation|updated)\b", re.I)
# A specification the model put in "verify" instead of "value" ("Has to be between 410 and 426").
_SPEC_IN_VERIFY = re.compile(r"(?:has to be|supposed to be|should be|must be)?\s*between\s+(\d+(?:\.\d+)?)\s+(?:and|to)\s+(\d+(?:\.\d+)?)", re.I)


def _secs(ts):
    try:
        m, s = str(ts).strip().strip('[]').split(':')[-2:]
        return int(m) * 60 + int(float(s))
    except (ValueError, TypeError):
        return None


def _clean_steps(steps, segments):
    """Make AI steps reliable: drop junk notes, merge duplicates/near-duplicates,
    and flag silent gaps in the recording (computed from the transcript, not guessed by the AI)."""
    out = []
    for raw in steps:
        if not isinstance(raw, dict):
            continue
        st = {k: str(raw.get(k) or '').strip() for k in ('timestamp', 'title', 'detail', 'value', 'verify')}
        if not st['title']:
            continue
        spec = _SPEC_IN_VERIFY.search(st['verify'])
        if spec:
            rng = f'{spec.group(1)}-{spec.group(2)}'
            st['value'] = f"{st['value']}; spec {rng}" if st['value'] else rng
            st['verify'] = ''
        if _JUNK_VERIFY.search(st['verify']):
            st['verify'] = ''
        prev = out[-1] if out else None
        t, pt = _secs(st['timestamp']), _secs(prev['timestamp']) if prev else None
        same = prev and st['title'].lower() == prev['title'].lower()
        close = prev and t is not None and pt is not None and t - pt < 10 and len(prev['title']) + len(st['title']) < 90
        if prev and (same or close):
            if not same and len(st['title'].split()) >= 3 and len(prev['title'].split()) >= 3:
                prev['title'] += ', then ' + st['title'][0].lower() + st['title'][1:]
            elif len(st['title']) > len(prev['title']):
                prev['title'] = st['title']
            if st['detail'] and st['detail'] not in prev['detail']:
                prev['detail'] = (prev['detail'] + ' ' if prev['detail'] else '') + st['detail']
            for k in ('value', 'verify'):
                if st[k] and st[k] not in prev[k]:
                    prev[k] = (prev[k] + '; ' if prev[k] else '') + st[k]
            continue
        out.append(st)
    # Silent gaps of 30 s or more between spoken segments are attached to the step they fall in.
    for (a_start, a_end), (b_start, _) in zip(segments, segments[1:]):
        if b_start - a_end >= 30 and out:
            owner = out[0]
            for st in out:
                ts = _secs(st['timestamp'])
                if ts is not None and ts <= a_end:
                    owner = st
            note = f'{stamp(a_end)}-{stamp(b_start)} silent; confirm actions on video'
            owner['verify'] = (owner['verify'] + '; ' if owner['verify'] else '') + note
    for st in out:
        st['requires_review'] = bool(st['verify'])
    return out


def generate_sop(v):
    src = [s for s in v.steps if s.kind == 'transcript'] or list(v.steps)
    segments = [(float(s.start_sec or 0), float(s.end_sec or 0)) for s in src]

    class _Row:
        def __init__(self, start, end, text):
            self.start_sec, self.end_sec, self.text = start, end, text
    # Whisper splits speech into fragments ("Past", "rubber", "Id"). Join fragments that run
    # together (pause under 4 s, passage under 30 s) so the model reads whole sentences.
    rows = []
    for s_ in src:
        text = (s_.body if s_.kind == 'transcript' else f'{s_.title}: {s_.body}').strip()
        if rows and float(s_.start_sec or 0) - rows[-1].end_sec < 4 and float(s_.start_sec or 0) - rows[-1].start_sec < 30:
            rows[-1].text += ' ' + text
            rows[-1].end_sec = float(s_.end_sec or s_.start_sec or 0)
        else:
            rows.append(_Row(float(s_.start_sec or 0), float(s_.end_sec or s_.start_sec or 0), text))
    lines = [f'[{stamp(r.start_sec)}] {r.text}' for r in rows]
    if not ''.join(lines).strip():
        raise RuntimeError('Transcribe the video or add steps before generating an SOP.')
    if not ai_configured():
        raise RuntimeError('AI report generation is not configured. Set AI_PROVIDER, AI_API_KEY, and AI_MODEL in your environment.')
    endpoint = os.getenv('AI_BASE_URL', 'https://api.openai.com/v1/chat/completions').rstrip('/')
    if not endpoint.endswith('/chat/completions'):
        endpoint += '/chat/completions'

    def ask(part, target, label):
        system = SOP_SYSTEM_PROMPT.replace('{target}', str(target))
        payload = {'model': os.getenv('AI_MODEL'), 'temperature': 0.1, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': f'Video: {v.title}{label}\nTranscript:\n{part}'}], 'response_format': {'type': 'json_object'}}
        req = Request(endpoint, data=json.dumps(payload).encode(), headers={'Authorization': 'Bearer ' + os.getenv('AI_API_KEY', 'ollama'), 'Content-Type': 'application/json', 'Accept': 'application/json'}, method='POST')
        try:
            with urlopen(req, timeout=int(os.getenv('AI_TIMEOUT_SECONDS', '120'))) as res:
                data = json.loads(res.read().decode())
            content = (data['choices'][0]['message'].get('content') or '').strip()
            if content.startswith('```'):
                content = re.sub(r'^```(?:json)?\s*|\s*```$', '', content, flags=re.I).strip()
            result = json.loads(content)
        except (HTTPError, URLError, TimeoutError, KeyError, ValueError) as e:
            raise RuntimeError(f'AI report generation failed: {e}') from e
        if not isinstance(result.get('steps'), list):
            raise RuntimeError('AI provider returned an invalid SOP structure.')
        return result

    # Long transcripts are sent in parts so a small local model never reads more than it can hold.
    # Each part gets a step budget of roughly one step per 45 seconds of video.
    limit = int(os.getenv('AI_CHUNK_CHARS', '5000'))
    parts, cur, cur_rows = [], [], []
    for line, row in zip(lines, rows):
        if cur and sum(len(x) for x in cur) + len(line) > limit:
            parts.append((cur, cur_rows))
            cur, cur_rows = [], []
        cur.append(line)
        cur_rows.append(row)
    if cur:
        parts.append((cur, cur_rows))
    merged = None
    for n, (part_lines, part_rows) in enumerate(parts, 1):
        span = max(0.0, float(part_rows[-1].end_sec or part_rows[-1].start_sec or 0) - float(part_rows[0].start_sec or 0))
        target = max(2, round(span / 45))
        label = '' if len(parts) == 1 else f' (part {n} of {len(parts)}; continue the same procedure)'
        app.logger.info('Generating SOP part %s of %s (~%s steps)', n, len(parts), target)
        result = ask('\n'.join(part_lines), target, label)
        if merged is None:
            merged = result
        else:
            merged['steps'].extend(result['steps'])
    merged['steps'] = _clean_steps(merged['steps'], segments)
    # Retain teammate's review fields while adapting to the studio document UI/PDF.
    for step in merged['steps']:
        step['description'] = step.get('detail', '')
        step['notes'] = '; '.join(x for x in [step.get('value', ''), step.get('verify', '')] if x)
        step['expected_result'] = step.get('value', '')
    merged.setdefault('video_title', v.title)
    merged.setdefault('purpose', merged.get('overview', ''))
    merged.setdefault('prerequisites', [])
    merged.setdefault('warnings', [])
    merged.setdefault('outcome', '')
    merged.setdefault('summary', '')
    return merged

@app.get('/api/videos/<vid>/report')
@login_required
def get_report(vid):
    v = owner_video(vid)
    r = Report.query.filter_by(video_id=vid, user_id=current_user.id).order_by(Report.updated_at.desc()).first()
    return jsonify(configured=ai_configured(), report={'id': r.id, 'title': r.title, 'content': json.loads(r.content_json)} if r else None)

@app.post('/api/videos/<vid>/report/generate')
@login_required
def generate_report(vid):
    v = owner_video(vid)
    try:
        content = generate_sop(v)
    except RuntimeError as e:
        return (jsonify(error=str(e)), 503)
    r = Report(video_id=vid, user_id=current_user.id, title=str(content.get('document_title') or v.title + ' SOP')[:200], content_json=json.dumps(content), source='ai')
    db.session.add(r)
    db.session.commit()
    try:
        pdf = make_pdf(v, content)
        (REPORTS / f'report-{r.id}.pdf').write_bytes(pdf.getvalue())
    except Exception:
        app.logger.exception('Could not cache generated SOP PDF')
    return (jsonify(id=r.id, title=r.title, content=content), 201)

@app.get('/api/reports/<int:rid>')
@login_required
def report_detail(rid):
    r = db.session.get(Report, rid)
    if not r or r.user_id != current_user.id:
        abort(404)
    return jsonify(id=r.id, title=r.title, video_id=r.video_id, content=json.loads(r.content_json))

@app.put('/api/reports/<int:rid>')
@login_required
def edit_report(rid):
    r = db.session.get(Report, rid)
    if not r or (r.user_id != current_user.id and current_user.role != 'admin'):
        abort(404)
    d = request.get_json(silent=True) or {}
    c = d.get('content')
    if not isinstance(c, dict) or not isinstance(c.get('steps'), list):
        return (jsonify(error='Invalid SOP structure.'), 400)
    r.content_json = json.dumps(c)
    r.title = str(c.get('document_title') or r.title)[:200]
    r.source = 'edited'
    db.session.commit()
    try:
        v = owner_video(r.video_id)
        (REPORTS / f'report-{r.id}.pdf').write_bytes(make_pdf(v, c).getvalue())
    except Exception:
        app.logger.exception('Could not refresh cached SOP PDF')
    return jsonify(ok=True)

def make_pdf(v, c):
    buf = io.BytesIO()
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='SOPTitle', parent=styles['Title'], fontSize=22, leading=27, textColor=colors.HexColor('#15324b'), alignment=0, spaceAfter=12))
    styles.add(ParagraphStyle(name='StepHeading', parent=styles['Heading2'], fontSize=13, leading=17, textColor=colors.HexColor('#145da0'), spaceBefore=12, spaceAfter=5, keepWithNext=True))
    styles['BodyText'].leading = 15
    styles['BodyText'].spaceAfter = 7

    def p(t, sty='BodyText'):
        return Paragraph(escape(str(t or 'Not identifiable from transcript — review required')).replace('\n', '<br/>'), styles[sty])

    def footer(can, doc):
        can.saveState()
        can.setStrokeColor(colors.HexColor('#dbe3ec'))
        can.line(42, 38, A4[0] - 42, 38)
        can.setFont('Helvetica', 8)
        can.setFillColor(colors.HexColor('#607286'))
        can.drawString(42, 25, 'Training Video Workspace • SOP draft for human review')
        can.drawRightString(A4[0] - 42, 25, f'Page {doc.page}')
        can.restoreState()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=48, bottomMargin=55, title=str(c.get('document_title') or v.title))
    story = [p(c.get('document_title') or v.title, 'SOPTitle'), p('STANDARD OPERATING PROCEDURE', 'Heading2'), p('Video: ' + v.title), p('Source file: ' + v.filename)]
    for h, k in [('Process overview', 'overview'), ('Purpose', 'purpose'), ('Required tools and prerequisites', 'prerequisites'), ('Warnings and important notes', 'warnings')]:
        story.append(p(h, 'Heading2'))
        value = c.get(k) or ['Not identifiable from transcript — review required'] if k in ('prerequisites', 'warnings') else c.get(k)
        if isinstance(value, list):
            story.extend((p('• ' + str(x)) for x in value))
        else:
            story.append(p(value))
    story.append(p('Step-by-step instructions', 'Heading1'))
    for i, s in enumerate(c.get('steps', []), 1):
        block = [p(f"Step {i} — {s.get('title', 'Untitled')} | {s.get('timestamp', 'Review required')}", 'StepHeading'), p(s.get('description'))]
        if s.get('notes'):
            block.append(p('Note: ' + str(s['notes'])))
        if s.get('expected_result'):
            block.append(p('Expected result: ' + str(s['expected_result'])))
        if s.get('requires_review'):
            block.append(p('REVIEW REQUIRED: Verify this step against the source video.'))
        story.append(KeepTogether(block))
    story.extend([p('Expected overall outcome', 'Heading2'), p(c.get('outcome')), p('Process summary', 'Heading2'), p(c.get('summary'))])
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    buf.seek(0)
    return buf

@app.get('/videos/<vid>/transcript')
@login_required
def transcript_page(vid):
    owner_video(vid)
    return render_template('video_results.html', mode='transcript', video_id=vid)

@app.get('/videos/<vid>/clips')
@login_required
def clips_page(vid):
    owner_video(vid)
    return render_template('video_results.html', mode='clips', video_id=vid)

@app.get('/reports')
@login_required
def reports_page():
    return render_template('reports.html')

@app.get('/api/reports')
@login_required
def reports_api():
    q = Report.query if current_user.role == 'admin' else Report.query.filter_by(user_id=current_user.id)
    return jsonify([{'id': r.id, 'video_id': r.video_id, 'title': r.title, 'updated_at': r.updated_at.isoformat()} for r in q.order_by(Report.updated_at.desc()).all()])

@app.delete('/api/reports/<int:rid>')
@login_required
def delete_report(rid):
    r = db.session.get(Report, rid)
    if not r or (r.user_id != current_user.id and current_user.role != 'admin'):
        abort(404)
    path = (REPORTS / f'report-{r.id}.pdf').resolve()
    if path.parent == REPORTS.resolve():
        path.unlink(missing_ok=True)
    db.session.delete(r)
    db.session.commit()
    return ('', 204)

@app.get('/api/reports/<int:rid>/pdf')
@login_required
def report_pdf(rid):
    r = db.session.get(Report, rid)
    if not r or (r.user_id != current_user.id and current_user.role != 'admin'):
        abort(404)
    v = owner_video(r.video_id)
    path = REPORTS / f'report-{r.id}.pdf'
    if not path.is_file():
        path.write_bytes(make_pdf(v, json.loads(r.content_json)).getvalue())
    return send_file(path, mimetype='application/pdf', as_attachment=True, download_name=secure_filename(r.title or 'training-sop') + '.pdf')

@app.get('/api/videos/<vid>/pdf')
@login_required
def export_pdf(vid):
    v = owner_video(vid)
    c = {'document_title': v.title + ' — Standard Operating Procedure', 'overview': 'Draft instructions assembled from saved steps. Review before use.', 'purpose': 'Document the process demonstrated in the training video.', 'prerequisites': [], 'warnings': [], 'steps': [{'title': s.title, 'timestamp': stamp(s.start_sec), 'description': s.body, 'requires_review': s.kind == 'transcript'} for s in v.steps], 'outcome': 'Verify the result against the source video.', 'summary': 'Review all steps and confirm them against the video.'}
    return send_file(make_pdf(v, c), mimetype='application/pdf', as_attachment=True, download_name=secure_filename(v.title) + '-SOP.pdf')

@app.errorhandler(403)
def forbidden(_):
    return (render_template('error.html', code=403, message='You do not have permission to access this page.'), 403)

@app.errorhandler(404)
def missing(_):
    return (render_template('error.html', code=404, message='The requested item was not found or is not available in your workspace.'), 404)

@app.errorhandler(413)
def too_large(_):
    return (jsonify(error='Video exceeds the configured upload limit.'), 413)

@app.after_request
def headers(r):
    r.headers.setdefault('X-Content-Type-Options', 'nosniff')
    r.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    r.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    return r
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', '5000')), debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')

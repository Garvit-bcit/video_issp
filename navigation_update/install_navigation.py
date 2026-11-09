from pathlib import Path
import shutil

ROUTE="@app.get('/api/videos/<vid>/outputs')\n@login_required\ndef video_outputs(vid):\n    v = owner_video(vid)\n    has_report = Report.query.filter_by(video_id=v.id, user_id=current_user.id).first() is not None\n    # The existing clips endpoint is the authority on clip availability.\n    manifest_path = VIDEOS / 'clips' / v.id / 'manifest.json'\n    has_clips = False\n    if manifest_path.is_file():\n        try:\n            has_clips = bool(json.loads(manifest_path.read_text(encoding='utf-8')).get('clips'))\n        except (OSError, ValueError, TypeError):\n            pass\n    return jsonify(transcript=any(s.kind == 'transcript' for s in v.steps),\n                   sop=has_report, clips=has_clips, status=v.status)\n\n"
LIBRARY="@app.get('/library/<kind>')\n@login_required\ndef results_library(kind):\n    if kind not in ('clips', 'transcripts'):\n        abort(404)\n    return render_template('results_library.html', kind=kind)\n\n"
root=Path(__file__).resolve().parent
project=Path.cwd()
app_file=project/'app.py'
if not app_file.exists() or not (project/'templates/base.html').exists():
    raise SystemExit('Run this from your training-operations-studio project directory.')
source=app_file.read_text(encoding='utf-8')
marker="@app.get('/api/videos/<vid>/report')"
lib_marker="@app.get('/reports')"
if "def video_outputs(vid):" not in source:
    if marker not in source: raise SystemExit('Unexpected app.py structure; no files changed.')
    source=source.replace(marker, ROUTE+marker,1)
if "def results_library(kind):" not in source:
    if lib_marker not in source: raise SystemExit('Unexpected app.py structure; no files changed.')
    source=source.replace(lib_marker, LIBRARY+lib_marker,1)
# Back up before touching any existing files.
backup=project/'navigation_backup'
backup.mkdir(exist_ok=True)
for rel in ['app.py','templates/base.html','static/app.js','static/reports.js','static/video_results.js','static/style.css']:
    src=project/rel
    if src.exists():
        dst=backup/rel;dst.parent.mkdir(parents=True,exist_ok=True)
        if not dst.exists(): shutil.copy2(src,dst)
app_file.write_text(source,encoding='utf-8')
for rel in ['templates/base.html','templates/results_library.html','static/app.js','static/reports.js','static/video_results.js','static/results_library.js']:
    dst=project/rel;dst.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(root/rel,dst)
# Append CSS, retaining the project's own styles.
css=project/'static/style.css'
extra=(root/'static/navigation_extra.css').read_text(encoding='utf-8')
current=css.read_text(encoding='utf-8')
if '/* Navigation-only improvements */' not in current:
    css.write_text(current+'\n'+extra,encoding='utf-8')
print('Navigation update installed. Existing .env, Docker settings and session cookie names preserved.')
print('Backup:',backup)

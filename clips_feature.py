"""Optional AI-assisted short training clips for the Training Video Workspace."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from flask import Blueprint, abort, jsonify, send_file
from flask_login import login_required


def install_clips(app, owner_video, videos_dir):
    bp = Blueprint('clips', __name__)
    root = Path(videos_dir).resolve() / 'clips'
    root.mkdir(parents=True, exist_ok=True)

    def clip_dir(vid):
        return root / vid  # vid is validated through owner_video, a UUID in the DB

    def manifest(v):
        p = clip_dir(v.id) / 'manifest.json'
        if not p.is_file():
            return []
        return json.loads(p.read_text(encoding='utf-8'))['clips']

    @bp.get('/api/videos/<vid>/clips')
    @login_required
    def list_clips(vid):
        v = owner_video(vid)
        return jsonify(clips=manifest(v))

    @bp.get('/api/videos/<vid>/clips/<int:index>/file')
    @login_required
    def clip_file(vid, index):
        v = owner_video(vid)
        clips = manifest(v)
        if index < 1 or index > len(clips):
            abort(404)
        p = clip_dir(v.id) / f'clip-{index:02}.mp4'
        if not p.is_file():
            abort(404)
        return send_file(p, mimetype='video/mp4', conditional=True)

    @bp.post('/api/videos/<vid>/clips/generate')
    @login_required
    def generate_clips(vid):
        v = owner_video(vid)
        segments = [s for s in v.steps if s.kind == 'transcript' and s.body.strip()]
        if not segments:
            return jsonify(error='Transcribe this video before generating clips.'), 400
        duration = float(v.duration or 0)
        if not (0 < duration <= 14400):
            return jsonify(error='Video duration must be between 0 and 4 hours.'), 400
        if not os.getenv('AI_API_KEY') or not os.getenv('AI_MODEL'):
            return jsonify(error='Configure the AI provider first.'), 400
        source = (Path(videos_dir).resolve() / v.filename).resolve()
        if source.parent != Path(videos_dir).resolve() or not source.is_file():
            abort(404)

        # Ask Groq for boundaries; do not trust its times without validation.
        transcript = '\n'.join(f'[{s.start_sec:.1f}-{s.end_sec:.1f}] {s.body}' for s in segments)
        if len(transcript) > 30000:
            return jsonify(error='Transcript too long for this prototype (30,000 characters).'), 400
        prompt = (
            'Divide this training transcript into 2 to 6 coherent, consecutive lessons. '
            'Return ONLY JSON: {"clips":[{"title":"...","start":0.0,"end":60.0,"summary":"..."}]}. '
            'Start and end are seconds from the ORIGINAL video. Cover the video in order without overlaps, '
            'and use the transcript timestamps. Each lesson should be about 20 to 180 seconds when possible. '
            'Do not invent content. Keep titles and summaries brief.\n'
            f'Video duration: {duration:.1f} seconds\nTranscript:\n{transcript}'
        )
        base = os.getenv('AI_BASE_URL', '').rstrip('/')
        if not (base.startswith('https://') or base == 'http://ollama:11434/v1'):
            return jsonify(error='AI_BASE_URL must use HTTPS or the internal Ollama service.'), 400
        endpoint = base if base.endswith('/chat/completions') else base + '/chat/completions'
        payload = {'model': os.getenv('AI_MODEL'), 'messages': [
            {'role': 'system', 'content': 'Produce a single valid JSON object with a clips array. No markdown or commentary.'},
            {'role': 'user', 'content': prompt}],
            'response_format': {'type': 'json_object'},
            'max_tokens': 2048}
        try:
            # A second attempt without JSON mode handles providers that reject JSON mode.
            suggested = None
            last_issue = 'No usable JSON clip plan returned.'
            for attempt in range(2):
                current_payload = dict(payload)
                if attempt:
                    current_payload.pop('response_format', None)
                    current_payload['messages'] = [
                        {'role': 'system', 'content': 'Return ONLY JSON. Begin with { and end with }. No code fences.'},
                        {'role': 'user', 'content': prompt}]
                req = Request(endpoint, data=json.dumps(current_payload).encode('utf-8'), method='POST', headers={
                    'Authorization': 'Bearer ' + os.environ['AI_API_KEY'],
                    'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'curl/8.0'})
                try:
                    with urlopen(req, timeout=int(os.getenv('AI_TIMEOUT_SECONDS', '600'))) as response:
                        data = json.load(response)
                except HTTPError as e:
                    # Retry JSON validation failures without enforced JSON mode.
                    detail = e.read().decode('utf-8', errors='replace')
                    if attempt == 0 and e.code == 400 and 'json_validate_failed' in detail:
                        last_issue = 'Provider could not validate JSON on first attempt.'
                        continue
                    app.logger.warning('Clip AI HTTP error: %s (%s)', e.code, detail[:180])
                    return jsonify(error=f'AI API returned HTTP {e.code}. Check model and free-tier limits.'), 502
                message = data.get('choices', [{}])[0].get('message') or {}
                raw = message.get('content') or ''
                raw = raw.strip()
                if not raw:
                    last_issue = 'AI returned an empty clip plan.'
                    continue
                raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw, flags=re.I).strip()
                try:
                    plan = json.loads(raw)
                    suggested = plan['clips']
                    break
                except (ValueError, KeyError, TypeError):
                    # Some models wrap JSON in prose despite explicit instructions.
                    left, right = raw.find('{'), raw.rfind('}')
                    if left >= 0 and right > left:
                        try:
                            suggested = json.loads(raw[left:right + 1])['clips']
                            break
                        except (ValueError, KeyError, TypeError):
                            pass
                    last_issue = 'AI returned text instead of a valid JSON clip plan.'
            if suggested is None:
                raise ValueError(last_issue + ' Try a shorter video or another Groq model.')
            if not isinstance(suggested, list) or not (1 <= len(suggested) <= 8):
                raise ValueError('AI returned an invalid number of clips.')
            boundaries = []
            for c in suggested:
                start, end = float(c['start']), float(c['end'])
                if not (0 <= start < end <= duration + 1):
                    raise ValueError('AI returned invalid timestamps.')
                boundaries.append((start, min(end, duration), str(c.get('title') or 'Lesson')[:100], str(c.get('summary') or '')[:500]))
            boundaries.sort(key=lambda x: x[0])
            if any(boundaries[i][1] > boundaries[i + 1][0] + 0.1 for i in range(len(boundaries) - 1)):
                raise ValueError('AI returned overlapping clips.')
        except HTTPError as e:
            app.logger.warning('Clip AI HTTP error: %s', e.code)
            return jsonify(error=f'AI API returned HTTP {e.code}. Check model and rate limits.'), 502
        except (URLError, TimeoutError) as e:
            app.logger.warning('Clip AI connection error: %s', type(e).__name__)
            return jsonify(error='AI connection failed or timed out.'), 502
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as e:
            return jsonify(error=f'AI clip plan needs review: {e}'), 422

        folder = clip_dir(v.id)
        folder.mkdir(parents=True, exist_ok=True)
        clips = []
        # Render to a temporary directory first, preserving any previous successful clips.
        with tempfile.TemporaryDirectory(prefix='clip-build-', dir=folder) as tmp:
            temp = Path(tmp)
            try:
                for i, (start, end, title, summary) in enumerate(boundaries, 1):
                    output = temp / f'clip-{i:02}.mp4'
                    subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                        '-ss', str(start), '-i', str(source), '-t', str(end - start),
                        '-c:v', 'libx264', '-preset', 'veryfast', '-c:a', 'aac',
                        '-movflags', '+faststart', str(output)],
                        check=True, capture_output=True, timeout=900)
                    clips.append({'index': i, 'title': title, 'summary': summary,
                                  'start': round(start, 2), 'end': round(end, 2),
                                  'url': f'/api/videos/{v.id}/clips/{i}/file'})
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                app.logger.exception('Clip rendering failed')
                return jsonify(error='FFmpeg could not render the clips. Check the server logs.'), 500
            # Replace files only after all renders succeeded.
            for old in folder.glob('clip-*.mp4'):
                old.unlink()
            for i in range(1, len(clips) + 1):
                (temp / f'clip-{i:02}.mp4').replace(folder / f'clip-{i:02}.mp4')
            manifest_tmp = temp / 'manifest.json'
            manifest_tmp.write_text(json.dumps({'clips': clips}, indent=2), encoding='utf-8')
            manifest_tmp.replace(folder / 'manifest.json')
        return jsonify(clips=clips), 201

    app.register_blueprint(bp)

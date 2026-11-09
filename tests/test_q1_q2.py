"""Q1 + Q2 test suite for the Training Video Workspace (16 tests).

Q1 (technology-facing, 11 tests): unit, component and connectivity checks.
Q2 (business-facing, 5 tests): Given/When/Then story tests from the SFS worksheet.

Run from the project folder:  python -m unittest discover -s tests -v
The app is pointed at a throwaway database BEFORE it is imported, so real data is never touched.
Whisper and the AI service are simulated, so no sponsor data leaves the machine.
"""
import io, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

# ---------------------------------------------------------------- setup
ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix='vtw-tests-'))
os.environ.update({
    'DATA_DIR': str(TMP),
    'VIDEO_STORAGE': str(TMP / 'videos'),
    'REPORT_STORAGE': str(TMP / 'reports'),
    'DATABASE_URL': 'sqlite:///' + str(TMP / 'test.db'),
    'SECRET_KEY': 'test-secret-key-that-is-long-enough-123456',
    'BOOTSTRAP_ADMIN_USERNAME': '',
    'BOOTSTRAP_ADMIN_PASSWORD': '',
    'AI_API_KEY': '',
    'AI_MODEL': '',
    'DEPLOYMENT_MODE': 'test',
})
sys.path.insert(0, str(ROOT))

import app as appmod  # noqa: E402
from sqlalchemy import event, text  # noqa: E402

# Throwaway DB: skip disk syncs (fast on Windows) and wait on locks instead of hanging.
with appmod.app.app_context():
    @event.listens_for(appmod.db.engine, 'connect')
    def _fast_sqlite(dbapi_con, _):
        dbapi_con.execute('PRAGMA busy_timeout=30000')
        dbapi_con.execute('PRAGMA synchronous=OFF')
        dbapi_con.execute('PRAGMA journal_mode=MEMORY')
    appmod.db.engine.dispose()

PASSWORD = 'correct-horse-battery'


def fake_ai_response(content):
    """A fake urlopen() result shaped like an OpenAI chat-completions reply."""
    body = json.dumps({'choices': [{'message': {'content': json.dumps(content)}}]}).encode()
    res = mock.MagicMock()
    res.__enter__.return_value.read.return_value = body
    return res


class AppTestCase(unittest.TestCase):
    """Fresh database per test + helpers for users, videos, login and CSRF-protected requests."""

    def setUp(self):
        appmod.app.config['TESTING'] = True
        with appmod.app.app_context():
            appmod.db.session.remove()
            appmod.db.engine.dispose()
            appmod.db.drop_all()
            appmod.db.create_all()
        self.client = appmod.app.test_client()

    def make_user(self, name, role='user'):
        with appmod.app.app_context():
            u = appmod.User(username=name, role=role)
            u.set_password(PASSWORD)
            appmod.db.session.add(u)
            appmod.db.session.commit()
            return u.id

    def make_video(self, owner_id, duration=60.0):
        vid = 'a' * 32
        with appmod.app.app_context():
            appmod.db.session.add(appmod.Video(id=vid, user_id=owner_id, title='Setup changeover', filename=vid + '.mp4', duration=duration, status='ready'))
            appmod.db.session.commit()
        return vid

    def make_step(self, vid, body='Lift the guard.', start=5, kind='instruction', n=1):
        with appmod.app.app_context():
            appmod.db.session.add(appmod.Step(video_id=vid, position=n, start_sec=start, end_sec=start + 5, title=f'Section {n}', body=body, kind=kind))
            appmod.db.session.commit()

    def csrf(self):
        with self.client.session_transaction() as s:
            s.setdefault('_csrf_token', 'test-csrf-token')
            return s['_csrf_token']

    def login(self, name):
        self.client = appmod.app.test_client()
        return self.client.post('/login', data={'username': name, 'password': PASSWORD, '_csrf_token': self.csrf()})

    def send(self, method, url, **kw):
        headers = kw.pop('headers', {})
        headers['X-CSRF-Token'] = self.csrf()
        return getattr(self.client, method)(url, headers=headers, **kw)

    def upload(self, title='Line 3 changeover'):
        with mock.patch.object(appmod, 'ffprobe', return_value=90.0):
            r = self.send('post', '/api/videos', data={'file': (io.BytesIO(b'v'), 'changeover.mp4'), 'title': title}, content_type='multipart/form-data')
        return r.get_json()['id']

    def simulate_transcript(self, vid):
        """Stands in for Whisper: two timestamped transcript sections."""
        self.make_step(vid, body='First lift the guard.', start=5, kind='transcript', n=1)
        self.make_step(vid, body='Then set the torque.', start=20, kind='transcript', n=2)


# Simulated AI output in the app's procedure format: one confident step and one the model is unsure about.
SIMULATED_SOP = {
    'document_title': 'Machine Changeover SOP', 'overview': 'Changeover on line 3.',
    'steps': [
        {'timestamp': '00:05', 'title': 'Open guard', 'value': '', 'verify': '', 'requires_review': False},
        {'timestamp': '00:20', 'title': 'Set torque on M8 bolts', 'value': '', 'verify': 'Torque value not heard; confirm specification', 'requires_review': True},
    ],
}
AI_ON = {'AI_API_KEY': 'k', 'AI_MODEL': 'm'}


# ================================================================ Q1: technology-facing (11)

class Q1_Unit(AppTestCase):
    """Single functions in isolation."""

    def test_password_is_hashed_and_verifies(self):
        u = appmod.User(username='x')
        u.set_password('a-strong-password')
        self.assertNotIn('a-strong-password', u.password_hash)
        self.assertTrue(u.check_password('a-strong-password'))
        self.assertFalse(u.check_password('wrong'))

    @mock.patch.dict('os.environ', AI_ON)
    def test_malformed_ai_reply_is_rejected(self):
        vid = self.make_video(self.make_user('alice'))
        self.make_step(vid, kind='transcript')
        with appmod.app.app_context(), mock.patch.object(appmod, 'urlopen', return_value=fake_ai_response({'steps': 'oops'})):
            with self.assertRaisesRegex(RuntimeError, 'invalid SOP structure'):
                appmod.generate_sop(appmod.db.session.get(appmod.Video, vid))

    def test_pdf_is_generated(self):
        vid = self.make_video(self.make_user('alice'))
        content = {'document_title': 'Torque <M8> & "bolts"', 'steps': [{'title': 'Open guard', 'requires_review': True}]}
        with appmod.app.app_context():
            pdf = appmod.make_pdf(appmod.db.session.get(appmod.Video, vid), content).getvalue()
        self.assertTrue(pdf.startswith(b'%PDF'))


class Q1_Component(AppTestCase):
    """Routes and database together, through Flask's test client."""

    def test_pages_require_login(self):
        for url in ('/', '/reports', '/api/videos'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn('/login', r.headers['Location'])

    def test_wrong_password_fails(self):
        self.make_user('alice')
        self.client.post('/login', data={'username': 'alice', 'password': 'nope', '_csrf_token': self.csrf()})
        self.assertEqual(self.client.get('/api/videos').status_code, 302)

    def test_post_without_csrf_token_is_rejected(self):
        self.make_user('alice')
        self.login('alice')
        self.assertEqual(self.client.post('/api/videos', data={}).status_code, 400)

    def test_normal_user_gets_403_on_admin_panel(self):
        self.make_user('alice')
        self.login('alice')
        self.assertEqual(self.client.get('/admin').status_code, 403)

    def test_other_users_video_returns_404(self):
        vid = self.make_video(self.make_user('alice'))
        self.make_user('bob')
        self.login('bob')
        self.assertEqual(self.client.get(f'/api/videos/{vid}').status_code, 404)

    def test_invalid_steps_rejected(self):
        vid = self.make_video(self.make_user('alice'), duration=60)
        self.login('alice')
        cases = {
            'negative start': {'start_sec': -1},
            'end before start': {'start_sec': 20, 'end_sec': 10},
            'start past video end': {'start_sec': 120, 'end_sec': 125},
            'empty title': {'title': '  '},
        }
        for name, over in cases.items():
            payload = {'title': 'Open guard', 'body': 'Lift the guard.', 'start_sec': 5, 'end_sec': 10}
            payload.update(over)
            with self.subTest(name):
                self.assertEqual(self.send('post', f'/api/videos/{vid}/steps', json=payload).status_code, 400)


class Q1_Connectivity(unittest.TestCase):
    """Can the app reach what it depends on?"""

    def test_database_connection(self):
        with appmod.app.app_context():
            self.assertEqual(appmod.db.session.execute(text('SELECT 1')).scalar(), 1)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg not installed')
    def test_ffprobe_reads_a_real_clip(self):
        with tempfile.TemporaryDirectory() as tmp:
            clip = Path(tmp) / 'clip.mp4'
            subprocess.run(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'testsrc=duration=2:size=160x120:rate=10',
                            '-f', 'lavfi', '-i', 'sine=duration=2', '-shortest', str(clip)],
                           capture_output=True, check=True, timeout=60)
            self.assertAlmostEqual(appmod.ffprobe(clip), 2.0, delta=0.3)


# ================================================================ Q2: business-facing stories (5)

class Q2_Stories(AppTestCase):
    """User stories from the SFS CPRJ-2091 worksheet, written as Given/When/Then."""

    def setUp(self):
        super().setUp()
        self.make_user('operator')
        self.login('operator')

    def test_story1_given_uploaded_video_when_transcribed_then_steps_have_timestamps(self):
        """As an SME, I want my recording turned into a timestamped transcript."""
        vid = self.upload()
        self.simulate_transcript(vid)
        steps = self.client.get(f'/api/videos/{vid}').get_json()['steps']
        self.assertEqual([s['start_sec'] for s in steps], [5, 20])

    @mock.patch.dict('os.environ', AI_ON)
    def test_story2_given_transcript_when_generating_then_uncertain_steps_are_flagged(self):
        """As an SME, I want the AI to flag what it isn't sure about (criterion: Correction Effort)."""
        vid = self.upload()
        self.simulate_transcript(vid)
        with mock.patch.object(appmod, 'urlopen', return_value=fake_ai_response(SIMULATED_SOP)):
            r = self.send('post', f'/api/videos/{vid}/report/generate')
        self.assertEqual(r.status_code, 201)
        flagged = [s for s in r.get_json()['content']['steps'] if s['requires_review']]
        self.assertEqual([s['title'] for s in flagged], ['Set torque on M8 bolts'])
        self.assertTrue(flagged[0]['verify'])  # the reviewer is told what to confirm

    @mock.patch.dict('os.environ', AI_ON)
    def test_story3_given_ai_draft_when_sme_edits_then_export_contains_the_edit(self):
        """As a reviewer, nothing is exported without my approval (out of scope: auto-approve)."""
        vid = self.upload()
        self.simulate_transcript(vid)
        with mock.patch.object(appmod, 'urlopen', return_value=fake_ai_response(SIMULATED_SOP)):
            rid = self.send('post', f'/api/videos/{vid}/report/generate').get_json()['id']
        corrected = json.loads(json.dumps(SIMULATED_SOP))
        corrected['steps'][1].update(value='25 Nm', verify='', requires_review=False)
        self.assertEqual(self.send('put', f'/api/reports/{rid}', json={'content': corrected}).status_code, 200)
        saved = self.client.get(f'/api/videos/{vid}/report').get_json()['report']['content']['steps'][1]
        self.assertEqual(saved['value'], '25 Nm')  # the SME's correction is what's stored and exported
        with appmod.app.app_context():
            self.assertEqual(appmod.db.session.get(appmod.Report, rid).source, 'edited')
        pdf = self.client.get(f'/api/reports/{rid}/pdf')
        self.assertTrue(pdf.data.startswith(b'%PDF'))
        pdf.close()

    def test_story4_given_no_ai_service_then_manual_steps_and_pdf_still_work(self):
        """As SFS, the pilot must not be blocked while no AI service is approved."""
        vid = self.upload()
        r = self.send('post', f'/api/videos/{vid}/steps', json={'title': 'Open guard', 'body': 'Lift it.', 'start_sec': 5, 'end_sec': 8})
        self.assertEqual(r.status_code, 201)
        self.assertFalse(self.client.get(f'/api/videos/{vid}/report').get_json()['configured'])
        self.assertTrue(self.client.get(f'/api/videos/{vid}/pdf').data.startswith(b'%PDF'))

    def test_story5_given_two_operators_then_each_sees_only_their_own_videos(self):
        """As SFS, confidential footage is visible only to its owner (criterion: Data / Process Fit)."""
        mine = self.upload('Mine')
        self.make_user('other')
        self.login('other')
        self.assertEqual(self.client.get('/api/videos').get_json(), [])
        self.assertEqual(self.client.get(f'/api/videos/{mine}/file').status_code, 404)


if __name__ == '__main__':
    unittest.main()

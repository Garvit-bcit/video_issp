# Training Video Workspace: Q1 & Q2 Test Plan (CPRJ-2091)

This plan follows the Agile Testing Quadrants. Q1 and Q2 both **guide development**: they are written before or alongside the code.

| | Q1: Technology-facing | Q2: Business-facing |
|---|---|---|
| Audience | Developers | SFS sponsor / SMEs |
| Question | Does the code do what we built it to do? | Are we building what SFS asked for? |
| Form | Automated unit, component and connectivity tests | Story tests, examples, prototype/UX sessions, A/B comparison, simulations |

## How to run (Windows PowerShell, from the project folder)

```
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
```

The tests use a throwaway temp database, so `instance/` and real videos are never touched. All tests live in one file, `tests/test_q1_q2.py`. Current result: **16 tests (11 Q1 + 5 Q2), all pass.**

---

## Q1: Technology-facing tests (automated, 11)

| Class in `test_q1_q2.py` | Tests | What it covers |
|---|---|---|
| `Q1_Unit` | 3 | Password hashing; malformed AI reply rejected; PDF generated (with `< & "` characters) |
| `Q1_Component` | 6 | Login required; wrong password fails; CSRF rejection; normal user blocked from admin (403); **another user's video returns 404**; invalid steps rejected (4 cases) |
| `Q1_Connectivity` | 2 | Database `SELECT 1`; FFmpeg/ffprobe reads a generated 2-second clip |

### Defects found by Q1 probing (log as backlog items)

1. **Step end time is not checked against video length.** A 60-second video accepts `end_sec = 9999`. Fix: add `or end > v.duration + 1` to the checks in `add_step` / `update_step`.
2. **Admin can't see another user's report on the video page.** `get_report` filters by `user_id=current_user.id`, while other report routes allow admins. This is inconsistent; decide which behaviour is intended.
3. README says to run `tests/`, but the folder didn't exist. **Fixed** by this suite.
4. `.env` with a real `SECRET_KEY`, bootstrap admin password and Postgres password is **inside the shared ZIP**. Rotate those values and leave `.env` out of future ZIPs.

---

## Q2: Business-facing tests

### 1. Story tests (`Q2_Stories` in `test_q1_q2.py`, 5 automated tests written from the SFS worksheet)

| # | Story (Given / When / Then) | Worksheet link |
|---|---|---|
| S1 | **Given** an uploaded recording, **when** it is transcribed, **then** every section has a timestamp | Pilot Output |
| S2 | **Given** a transcript, **when** AI drafts the SOP, **then** steps it can't confirm are flagged `requires_review` | Correction Effort, Technical Accuracy |
| S3 | **Given** an AI draft, **when** the SME corrects it, **then** the saved report is marked `edited` and the PDF reflects the edit | SME review; Out of scope: auto-approve |
| S4 | **Given** no approved AI service, **then** manual steps and PDF export still work | Ease of Use, Data/Process Fit |
| S5 | **Given** two operators, **then** each sees only their own videos; admins see all | Data/Process Fit (confidentiality) |

### 2. Examples (agree these with the sponsor before the pilot)

| Domain | Input | Expected output | Pass if |
|---|---|---|---|
| Mfg. machine procedure | 3–5 min changeover recording with narration | Timestamped SOP PDF plus a short video clip | SME confirms the step order and every step links to the right moment |
| Quality SAP procedure | Screen recording of a SAP transaction with narration | Step-by-step quality work instruction | Silent clicks are flagged for review, not guessed |

### 3. Prototype and UX session (30 min, 2–3 SFS users, non-confidential sample video)

Tasks, observed and timed:

1. Sign in and upload a video.
2. Transcribe it and jump to 00:20 by clicking a step.
3. Add a missing step.
4. Fix one flagged AI step.
5. Download the PDF.

Record for each task whether it was completed without help, how long it took, and where the user hesitated.

### 4. A/B comparison (feeds the Week 9 "Results & lessons learned" deliverable)

| | A: Manual baseline | B: AI-assisted |
|---|---|---|
| Process | SME writes the SOP from the video by hand | Tool drafts it, SME reviews |
| Measure | Minutes to finished SOP | Minutes to finished SOP plus number of corrections |
| Judge | SME scores both on the 6 worksheet criteria (1–5) | Same |

Use the same video for both. Swap the order between SMEs.

### 5. Simulations

Story tests replace Whisper and the AI provider with **fixed simulated outputs**. This lets the business flow be checked without sponsor footage leaving the machine and without paid API keys. It matches the handover rule: *do not use confidential footage until access and approval are in place.*

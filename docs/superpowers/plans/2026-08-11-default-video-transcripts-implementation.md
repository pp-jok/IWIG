# Default Video Transcripts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local timestamped transcription the default for video capture so video breakdown packages have their required transcript input.

**Architecture:** `scripts/iwig.py` owns the capture default and forwards local ASR to `scripts/run_capture.py`. A cached video without a completed transcript runs local ASR against its existing video before the analysis index is rebuilt. The existing processing and readiness state reports an ASR failure without changing public-capture facts.

**Tech Stack:** Python 3.9, argparse, faster-whisper, unittest.

## Global Constraints

- Keep public-HTML-only collection and local-only ASR.
- Default video ASR uses CPU int8, model `small`, and language `zh`.
- `--no-transcribe` is the capture opt-out; image notes remain transcript-free.
- A video breakdown requires `readiness.transcript == "ready"`.

---

### Task 1: Default capture ASR and explicit opt-out

**Files:**

- Modify: `scripts/iwig.py:153-218`
- Test: `tests/test_iwig_cli.py`

**Interfaces:** Capture gains `--no-transcribe`. Default capture forwards `--transcribe`; opt-out does not.

- [ ] **Step 1: Write failing tests**

```python
def test_capture_transcribes_video_by_default(self):
    with patch.object(sys, "argv", ["iwig", "capture", "--url", "https://example.test/n"]), \
            patch("iwig.run_capture.main", return_value=0) as capture:
        iwig.main()
    self.assertIn("--transcribe", capture.call_args.args[0])

def test_capture_no_transcribe_is_an_explicit_opt_out(self):
    with patch.object(sys, "argv", ["iwig", "capture", "--url", "https://example.test/n", "--no-transcribe"]), \
            patch("iwig.run_capture.main", return_value=0) as capture:
        iwig.main()
    self.assertNotIn("--transcribe", capture.call_args.args[0])
```

- [ ] **Step 2: Verify red**

Run `python3 -m unittest tests.test_iwig_cli.IwigCliTests.test_capture_transcribes_video_by_default tests.test_iwig_cli.IwigCliTests.test_capture_no_transcribe_is_an_explicit_opt_out -v`.

Expected: default-forwarding test fails.

- [ ] **Step 3: Implement the minimum CLI change**

```python
capture.add_argument("--no-transcribe", action="store_true")
...
if not args.no_transcribe:
    forwarded += ["--transcribe"]
```

- [ ] **Step 4: Verify green and commit**

Run the Task 1 test command. Then run:

```bash
git add scripts/iwig.py tests/test_iwig_cli.py
git commit -m "feat: transcribe captured videos by default"
```

### Task 2: Complete missing transcripts for cached videos

**Files:**

- Modify: `scripts/iwig.py:180-198`
- Test: `tests/test_iwig_cli.py`

**Interfaces:** A cached run with a video record and non-completed `processing.transcribe` calls `run_capture.main(["--enrich-dir", str(existing), "--transcribe"])`; it never calls a provider capture function.

- [ ] **Step 1: Write a failing cache-resume test**

```python
def test_cached_video_without_transcript_runs_local_asr_without_recapture(self):
    package = new_content_package("completed", "https://example.test/n")
    package["media"]["video"] = {"path": "media/video.mp4"}
    atomic_write_json(run / "content_package.json", package)
    with patch("iwig.find_existing_package", return_value=run), \
            patch("iwig.run_capture.main", return_value=0) as local_stage:
        iwig.main()
    self.assertEqual(local_stage.call_args.args[0], ["--enrich-dir", str(run), "--transcribe"])
```

- [ ] **Step 2: Verify red**

Run `python3 -m unittest tests.test_iwig_cli.IwigCliTests.test_cached_video_without_transcript_runs_local_asr_without_recapture -v`.

Expected: it fails because cache reuse currently returns before ASR.

- [ ] **Step 3: Implement local-only continuation**

```python
stage = package.get("processing", {}).get("transcribe", {})
if package.get("media", {}).get("video") and stage.get("status") != "completed":
    run_capture.main(["--enrich-dir", str(existing), "--transcribe"])
    package, _ = migrate_content_package_in_memory(
        json.loads((existing / "content_package.json").read_text(encoding="utf-8"))
    )
```

- [ ] **Step 4: Verify green and commit**

Run the Task 2 test and `test_cached_capture_does_not_recapture_when_index_rebuild_fails`. Then commit:

```bash
git add scripts/iwig.py tests/test_iwig_cli.py
git commit -m "fix: complete transcript for cached videos"
```

### Task 3: Update user and downstream contract documentation

**Files:**

- Modify: `README.md:35-108`
- Modify: `SKILL.md:17-82`
- Test: `tests/test_public_html_provider.py`

**Interfaces:** Docs state that video capture transcribes by default, `--no-transcribe` opts out, and video breakdown requires transcript readiness.

- [ ] **Step 1: Write the failing documentation test**

```python
def test_skill_documents_default_video_transcription_and_breakdown_gate(self):
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    self.assertIn("--no-transcribe", text)
    self.assertIn("video breakdown requires transcript readiness", text)
```

- [ ] **Step 2: Verify red**

Run `python3 -m unittest tests.test_public_html_provider.BrowserRemovalTests.test_skill_documents_default_video_transcription_and_breakdown_gate -v`.

Expected: FAIL.

- [ ] **Step 3: Document default ASR and recovery**

Replace statements that capture never loads ASR with the default-video behavior. Document first model download, `--no-transcribe`, `enrich --transcribe` recovery, and the exact readiness requirement for video breakdown.

- [ ] **Step 4: Verify green and commit**

Run the Task 3 test. Then commit:

```bash
git add README.md SKILL.md tests/test_public_html_provider.py
git commit -m "docs: require transcripts for video breakdown"
```

### Task 4: Verify and publish

**Files:**

- Verify: `scripts/iwig.py`, `README.md`, `SKILL.md`, `tests/`

- [ ] **Step 1: Run regression suite**

Run `python3 -m unittest discover -s tests -v`.

Expected: all tests pass.

- [ ] **Step 2: Compile changed modules**

Run `PYTHONPYCACHEPREFIX=/private/tmp/iwig-pycache python3 -m py_compile scripts/iwig.py scripts/run_capture.py`.

Expected: exit code 0.

- [ ] **Step 3: Release hygiene**

Run `git diff --check && git status --short` and preserve unrelated untracked user files.

- [ ] **Step 4: Publish**

Run `git push git@github.com:pp-jok/IWIG.git main:main` and verify GitHub main equals local HEAD.

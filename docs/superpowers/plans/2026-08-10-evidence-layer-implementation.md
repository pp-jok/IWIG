# Evidence Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add factual, traceable visual and temporal evidence to each IWIG content package, plus an optional interpretation layer that never alters capture facts.

**Architecture:** Store OCR projections, scene candidates and evidence segments in `content_package.json` under `derived`, preserving source paths and timestamps. Project those records into the analysis index; optional labels are separate `kind: "inference"` records pointing to evidence IDs.

**Tech Stack:** Python 3, stdlib `unittest`, PyAV, macOS Vision OCR, JSON and Markdown.

## Global Constraints

- Read only public HTML and already downloaded local media: no browser automation, login, comments endpoints or private APIs.
- Preserve partial success; failed derived stages retain captured artifacts and a machine-readable reason.
- `jsonschema` remains optional; no new required runtime dependencies, including Pillow, cloud OCR or LLMs.
- Raw OCR, transcript and interval keyframes are facts; any threshold, score or label must disclose its basis and never overwrite raw values.
- Persist only run-relative POSIX paths, validated using existing safe-path helpers.

---

## File Structure

- `scripts/content_package.py`: pure OCR, scene-selection and evidence-segment functions; package defaults.
- `scripts/run_capture.py`: local-stage orchestration, artifact writing and stage state.
- `scripts/build_analysis_index.py`: read-only package-to-index projection.
- `tests/test_content_package.py`: unit and pipeline-state tests.
- `tests/test_build_analysis_index.py`: analysis index and inference-separation tests.
- `README.md`: artifacts and facts-versus-inferences contract.

### Task 1: Confidence-filtered OCR projection

**Files:**
- Modify: `scripts/content_package.py:418-430`
- Modify: `scripts/run_capture.py:98-133`
- Test: `tests/test_content_package.py`

**Interfaces:**
- Consumes: OCR records with `status`, raw `text`, and raw `lines`.
- Produces: `filtered_ocr_text(record: dict, minimum_confidence: float = 0.80) -> str`; every emitted OCR record adds `filtered_text` without changing raw fields.

- [ ] **Step 1: Write the failing tests**

```python
def test_filtered_ocr_text_keeps_only_confident_nonempty_lines(self):
    record = {"text": "原始", "lines": [
        {"text": "清晰标题", "confidence": .99},
        {"text": "误识别", "confidence": .31},
        {"text": " ", "confidence": 1.0},
    ]}
    self.assertEqual(filtered_ocr_text(record), "清晰标题")

def test_ocr_records_keep_raw_text_and_add_filtered_text(self):
    with patch("run_capture.ocr_macos_batch", return_value=[{
        "status": "available", "text": "标题\\n噪声",
        "lines": [{"text": "标题", "confidence": .95}, {"text": "噪声", "confidence": .2}],
    }]):
        records = _ocr_records(self.run, [{"path": "media/cover.jpg"}])
    self.assertEqual(records[0]["text"], "标题\\n噪声")
    self.assertEqual(records[0]["filtered_text"], "标题")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_content_package.ContentPackageTests.test_filtered_ocr_text_keeps_only_confident_nonempty_lines tests.test_content_package.ContentPackageTests.test_ocr_records_keep_raw_text_and_add_filtered_text -v`

Expected: failure because `filtered_ocr_text` or `filtered_text` is absent.

- [ ] **Step 3: Write minimal implementation**

```python
def filtered_ocr_text(record: dict, minimum_confidence: float = .80) -> str:
    return "\n".join(
        str(line.get("text", "")).strip() for line in record.get("lines") or []
        if str(line.get("text", "")).strip()
        and float(line.get("confidence", 0.0) or 0.0) >= minimum_confidence
    )

# At the end of _ocr_records:
for value in values:
    value["filtered_text"] = filtered_ocr_text(value)
return values
```

- [ ] **Step 4: Run all content-package tests**

Run: `python3 -m unittest tests.test_content_package -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/content_package.py scripts/run_capture.py tests/test_content_package.py
git commit -m "feat: add confidence-filtered OCR evidence"
```

### Task 2: Scene-change candidates

**Files:**
- Modify: `scripts/content_package.py:397-417`
- Modify: `scripts/run_capture.py:123-134`
- Test: `tests/test_content_package.py`

**Interfaces:**
- Consumes: frames with `id`, `time_seconds` and `adjacent_similarity`.
- Produces: `select_scene_change_frames(frames: list[dict], threshold: float = .72, limit: int = 6) -> list[dict]`; each item has `frame_ref`, `time_seconds`, `adjacent_similarity`, `selection_basis`, `threshold`.

- [ ] **Step 1: Write the failing test**

```python
def test_scene_change_selection_is_deterministic_and_explained(self):
    frames = [
        {"id": "frame-001", "time_seconds": 0, "adjacent_similarity": None},
        {"id": "frame-002", "time_seconds": 30, "adjacent_similarity": .88},
        {"id": "frame-003", "time_seconds": 60, "adjacent_similarity": .41},
        {"id": "frame-004", "time_seconds": 90, "adjacent_similarity": .66},
    ]
    selected = select_scene_change_frames(frames, threshold=.72, limit=2)
    self.assertEqual([x["frame_ref"] for x in selected], ["frame-003", "frame-004"])
    self.assertTrue(all(x["selection_basis"] == "adjacent_perceptual_hash" for x in selected))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_content_package.ContentPackageTests.test_scene_change_selection_is_deterministic_and_explained -v`

Expected: failure because the selector does not exist.

- [ ] **Step 3: Write minimal implementation and persist the additive field**

```python
def select_scene_change_frames(frames: list[dict], threshold: float = .72, limit: int = 6) -> list[dict]:
    candidates = [f for f in frames if f.get("adjacent_similarity") is not None and f["adjacent_similarity"] < threshold]
    candidates.sort(key=lambda f: (f["adjacent_similarity"], f.get("time_seconds", 0)))
    return [{"frame_ref": f["id"], "time_seconds": f["time_seconds"],
             "adjacent_similarity": f["adjacent_similarity"],
             "selection_basis": "adjacent_perceptual_hash", "threshold": threshold}
            for f in candidates[:limit]]

# In process_ocr_keyframes after selected_keyframes assignment:
result["derived"]["scene_change_keyframes"] = select_scene_change_frames(frames)
```

- [ ] **Step 4: Run content-package tests**

Run: `python3 -m unittest tests.test_content_package -v`

Expected: PASS; the existing `selected_keyframes` field remains unchanged.

- [ ] **Step 5: Commit**

```bash
git add scripts/content_package.py scripts/run_capture.py tests/test_content_package.py
git commit -m "feat: expose scene-change keyframe candidates"
```

### Task 3: Build factual evidence segments and persist an artifact

**Files:**
- Modify: `scripts/content_package.py:250-270`
- Modify: `scripts/run_capture.py:148-154`
- Test: `tests/test_content_package.py`

**Interfaces:**
- Consumes: transcript segments (`start`, `end`, `text`), keyframes, scene candidates and OCR records.
- Produces: `build_evidence_segments(transcript: list[dict], frames: list[dict], scene_candidates: list[dict], ocr: dict) -> list[dict]`, stored as `derived.evidence_segments` and `derived/evidence_segments.json`; each segment has `id`, `start`, `end`, `transcript_refs`, `frame_refs`, `ocr_refs`, `scene_candidate_refs`, `kind: "fact"`.

- [ ] **Step 1: Write the failing test**

```python
def test_evidence_segments_link_facts_without_semantic_claims(self):
    segments = build_evidence_segments(
        [{"id": "speech-001", "start": 0, "end": 8, "text": "今天讲三个方法"}],
        [{"id": "frame-001", "time_seconds": 3}],
        [{"frame_ref": "frame-001", "time_seconds": 3}],
        {"keyframes": [{"path": "derived/keyframes/001.jpg", "text": "三个方法"}]},
    )
    self.assertEqual(segments[0]["kind"], "fact")
    self.assertEqual(segments[0]["transcript_refs"], ["speech-001"])
    self.assertEqual(segments[0]["frame_refs"], ["frame-001"])
    self.assertNotIn("label", segments[0])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_content_package.ContentPackageTests.test_evidence_segments_link_facts_without_semantic_claims -v`

Expected: failure because `build_evidence_segments` does not exist.

- [ ] **Step 3: Implement bounded, factual segment construction**

```python
def build_evidence_segments(transcript, frames, scene_candidates, ocr):
    records = []
    for index, speech in enumerate(transcript, 1):
        start, end = speech.get("start", 0), speech.get("end", speech.get("start", 0))
        frame_refs = [f["id"] for f in frames if start <= f.get("time_seconds", -1) <= end]
        records.append({"id": f"evidence-{index:03}", "kind": "fact", "start": start, "end": end,
                        "transcript_refs": [speech["id"]] if speech.get("id") else [],
                        "frame_refs": frame_refs, "ocr_refs": [], "scene_candidate_refs": []})
    return records

# In process_local_stages after OCR, write with atomic_write_json and _stage:
segments = build_evidence_segments(result.get("transcript", []), frames, result["derived"].get("scene_change_keyframes", []), result["derived"].get("ocr", {}))
result["derived"]["evidence_segments"] = segments
atomic_write_json(run / "derived" / "evidence_segments.json", segments)
_stage(result, "build_evidence_segments", "completed", ["derived/evidence_segments.json"], "local factual linker")
```

- [ ] **Step 4: Run tests and inspect the artifact contract**

Run: `python3 -m unittest tests.test_content_package -v`

Expected: PASS; a package with no transcript produces an empty list and a `not_run`/`partial` stage reason rather than fabricated segments.

- [ ] **Step 5: Commit**

```bash
git add scripts/content_package.py scripts/run_capture.py tests/test_content_package.py
git commit -m "feat: add factual evidence segments"
```

### Task 4: Add an optional, explicitly inferred interpretation layer

**Files:**
- Modify: `scripts/content_package.py`
- Modify: `scripts/run_capture.py`
- Test: `tests/test_content_package.py`

**Interfaces:**
- Consumes: factual evidence segments.
- Produces: `rule_based_interpretations(segments: list[dict]) -> list[dict]`; each record has `id`, `kind: "inference"`, `label` from `hook|problem|case|method|result|call_to_action|unknown`, `confidence`, `evidence_refs`, `method: "rule_based_v1"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_interpretation_keeps_evidence_reference_and_declares_inference(self):
    items = rule_based_interpretations([{
        "id": "evidence-001", "kind": "fact", "start": 0, "end": 4,
        "transcript_text": "先说一个很多人都会遇到的问题",
    }])
    self.assertEqual(items[0]["kind"], "inference")
    self.assertEqual(items[0]["label"], "problem")
    self.assertEqual(items[0]["evidence_refs"], ["evidence-001"])
    self.assertEqual(items[0]["method"], "rule_based_v1")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest tests.test_content_package.ContentPackageTests.test_interpretation_keeps_evidence_reference_and_declares_inference -v`

Expected: failure because `rule_based_interpretations` does not exist.

- [ ] **Step 3: Implement conservative rules and opt-in orchestration**

```python
def rule_based_interpretations(segments: list[dict]) -> list[dict]:
    rules = [("problem", ("问题", "困扰")), ("method", ("方法", "步骤")),
             ("case", ("案例", "我之前")), ("call_to_action", ("关注", "评论"))]
    output = []
    for segment in segments:
        text = segment.get("transcript_text", "")
        label = next((name for name, words in rules if any(word in text for word in words)), "unknown")
        output.append({"id": f"inference-{segment['id']}", "kind": "inference", "label": label,
                       "confidence": .60 if label != "unknown" else .0, "evidence_refs": [segment["id"]],
                       "method": "rule_based_v1"})
    return output

# Add --interpret to enrich; when false record a not_run processing stage.
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_content_package -v`

Expected: PASS; capture and default enrich never create inference records.

- [ ] **Step 5: Commit**

```bash
git add scripts/content_package.py scripts/run_capture.py tests/test_content_package.py
git commit -m "feat: add opt-in evidence interpretations"
```

### Task 5: Project evidence into the analysis index and document the contract

**Files:**
- Modify: `scripts/public_html_provider.py:495-497`
- Modify: `scripts/build_analysis_index.py:26-66`
- Modify: `tests/test_build_analysis_index.py`
- Modify: `tests/test_public_html_provider.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `derived.evidence_segments`, `derived.scene_change_keyframes`, `derived.interpretations`, raw/filtered OCR and processing status.
- Produces: index fields `evidence_segments`, `scene_change_keyframes`, `interpretations`, and `analysis_readiness.evidence`; package status is internally consistent when capture completes.

- [ ] **Step 1: Write failing index and state-consistency tests**

```python
def test_index_projects_evidence_but_does_not_turn_inference_into_fact(self):
    package = new_content_package("completed", "https://www.xiaohongshu.com/explore/abc")
    package["derived"]["evidence_segments"] = [{"id": "evidence-001", "kind": "fact", "start": 0, "end": 4}]
    package["derived"]["interpretations"] = [{"id": "inference-evidence-001", "kind": "inference", "label": "hook", "evidence_refs": ["evidence-001"]}]
    index = build_analysis_index(self.run, package)
    self.assertEqual(index["evidence_segments"][0]["kind"], "fact")
    self.assertEqual(index["interpretations"][0]["kind"], "inference")

def test_successful_public_capture_syncs_capture_status(self):
    package = capture_public_note("https://www.xiaohongshu.com/explore/abc", client=self.client)
    self.assertEqual(package["status"], "completed")
    self.assertEqual(package["capture_status"], "completed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_build_analysis_index -v`

Expected: failure because the index does not project the new fields or package state is inconsistent.

- [ ] **Step 3: Implement read-only index projection and status synchronization**

```python
# Whenever capture_public_note assigns its terminal capture status:
result["status"] = "completed"
result["capture_status"] = "completed"
# Apply the same paired assignment for partial and failed terminal states.

# In build_analysis_index, add package projections without recomputation:
derived = package.get("derived", {})
index["evidence_segments"] = derived.get("evidence_segments", [])
index["scene_change_keyframes"] = derived.get("scene_change_keyframes", [])
index["interpretations"] = derived.get("interpretations", [])
index["analysis_readiness"]["evidence"] = "ready" if index["evidence_segments"] else "unavailable"
```

- [ ] **Step 4: Document concrete output and invocation**

```markdown
iwig enrich <run-dir> --keyframes --ocr
iwig enrich <run-dir> --keyframes --ocr --interpret

- `derived/evidence_segments.json`: factual transcript, frame and OCR links.
- `derived.scene_change_keyframes`: candidates selected by adjacent perceptual-hash threshold.
- `derived.interpretations`: opt-in rule-based hypotheses, always `kind: inference` with `evidence_refs`.
```

- [ ] **Step 5: Run complete regression and a real-package enrichment**

Run: `python3 -m unittest discover -s tests -v`

Expected: PASS with no newly introduced dependency.

Run: `python3 -m app.cli.main enrich /private/tmp/iwig-final-full-live --keyframes --ocr --interpret`

Expected: a regenerated `content_package.json`, `derived/evidence_segments.json`, keyframes/OCR retained, and no active error for a completed keyframe stage.

- [ ] **Step 6: Commit**

```bash
git add scripts/content_package.py scripts/build_analysis_index.py tests/test_build_analysis_index.py README.md
git commit -m "feat: expose evidence layer in analysis index"
```

## Final Verification Checklist

- [ ] `python3 -m unittest discover -s tests -v` passes.
- [ ] A video package can retain title, media, transcript, OCR and frames if a later optional stage fails.
- [ ] Raw OCR remains present and every filtered result identifies the fixed `0.80` confidence rule in documentation.
- [ ] Evidence segments contain only factual references; labels appear exclusively as `kind: "inference"` with evidence references.
- [ ] The analysis index is a projection, contains no network code and works without `jsonschema` installed.
- [ ] README explains artifacts, limits and the opt-in `--interpret` flag.

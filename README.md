# IWIG

Local-first public content capture and multimodal analysis packaging for Xiaohongshu.

IWIG converts one user-provided public Xiaohongshu note into a traceable local content package and analysis index. It never uses browser automation, cookies, login, JavaScript execution, private APIs, signatures, proxies, or hosted AI services.

```text
public note URL → public HTML provider → content_package.json → local media/ASR/OCR → analysis_index.json
```

## Install

```bash
git clone https://github.com/pp-jok/IWIG.git
cd IWIG
python3 scripts/iwig.py setup
```

The default local home is `~/.iwig` (override with `IWIG_HOME`).

## Use

```bash
~/.iwig/.venv/bin/python scripts/iwig.py capture --url 'https://www.xiaohongshu.com/explore/<NOTE_ID>' --keyframes --ocr
~/.iwig/.venv/bin/python scripts/iwig.py enrich ~/.iwig/output/<RUN_ID> --keyframes --ocr
~/.iwig/.venv/bin/python scripts/iwig.py enrich ~/.iwig/output/<RUN_ID> --keyframes --ocr --interpret
~/.iwig/.venv/bin/python scripts/iwig.py enrich ~/.iwig/output/<RUN_ID> --keyframes --ocr --interpret --describe-visuals
~/.iwig/.venv/bin/python scripts/iwig.py validate ~/.iwig/output/<RUN_ID>
~/.iwig/.venv/bin/python scripts/iwig.py reindex ~/.iwig/output/<RUN_ID>
```

`--json` emits one machine-readable result. The content package is the stable machine interface; `report.md` is only a human-readable summary. See [data contract](docs/data-contract.md), [analysis index](docs/analysis-index.md), and [migration](docs/migration-from-xhs-url-video-capture.md).

## Status semantics

`status` is the compatible alias of `capture_status`: it describes only the public-page and primary-media capture. `processing_status` describes local ASR, OCR, frames, timeline, and index processing separately. A machine result can therefore be:

```json
{"capture_status":"completed","processing_status":"partial","analysis_index_status":"failed","analysis_index":null}
```

Exit code `2` means local processing is incomplete; it does not mean the collected public content is unusable. Downstream tools must consume `analysis_index` only when `analysis_index_status` is `completed`. `reindex` is local-only and never revisits the platform.

## Output and boundaries

Each snapshot contains a schema-validated `content_package.json`, derived transcript/frames/OCR/timeline, and a local `derived/analysis_index.json`. Default manifests redact token-like URLs and media signatures. Raw source or sensitive candidates require explicit diagnostic flags and must not be committed.

Public `source/page.html` and `source/initial_state.json` are archived by default. The capture manifest is written before ASR/OCR begins, so an interrupted local stage can be resumed with `enrich` without revisiting the public page.

When local enrichment is available, IWIG also writes these evidence-layer artifacts:

- `derived/evidence_segments.json` links timestamped transcript segments to overlapping keyframes, keyframe OCR, and scene-change candidates. They are factual links only (`kind: "fact"`).
- `derived.scene_change_keyframes` records frames selected from adjacent perceptual-hash similarity, including the exact threshold and selection basis. It supplements, rather than replaces, interval and structural keyframes.
- OCR retains its provider text and line data; `filtered_text` is a reproducible view using lines with confidence at least `0.80`.
- `derived/interpretations.json` is created only by `enrich --interpret`. These are deliberately labelled `kind: "inference"`, include `evidence_refs`, and use the declared `rule_based_v1` method. They are hypotheses for downstream review, not captured facts.
- `derived/image_pages.json` preserves image-page order and page OCR references. `--describe-visuals` adds only rule-based visual inferences; it never changes captured facts.

If media, ASR, OCR, frames, or interpretation are unavailable, the package still preserves the completed stages and records the missing stage separately. Absence is never treated as a zero-valued public metric.

IWIG does not collect comment bodies, operate accounts, bypass access controls, construct media URLs, remove watermarks, or perform publishing actions. Follow platform terms, copyright, and applicable law.

## Development

```bash
python -m unittest discover -s tests -v
```

Live image-note validation is `pending_user_test`; IWIG never searches for validation posts on its own.

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

IWIG does not collect comment bodies, operate accounts, bypass access controls, construct media URLs, remove watermarks, or perform publishing actions. Follow platform terms, copyright, and applicable law.

## Development

```bash
python -m unittest discover -s tests -v
python -m py_compile scripts/*.py
```

Live image-note validation is `pending_user_test`; IWIG never searches for validation posts on its own.

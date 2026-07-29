# Public HTML Capture MVP

This isolated feasibility experiment requests one public Xiaohongshu link with
ordinary HTTPS. It does not use a browser, cookies, JavaScript execution,
private APIs, signatures, proxies, or anti-detection logic.

```bash
python3 -m pip install -r experiments/public_html_capture_mvp/requirements.txt
python3 experiments/public_html_capture_mvp/capture_public_mvp.py \
  --url 'http://xhslink.cn/o/yzHG8aTY0i' \
  --output-root experiments/public_html_capture_mvp/artifacts
```

Options: `--timeout` controls each HTTP operation, `--max-video-bytes` caps a
streamed media download, and `--force` permits creating an output root that
already exists. One run always writes `capture.json`, `run.log`, and
`validation_report.md`; it adds `page.html`, `initial_state.json`,
`video_candidates.json`, and `video.mp4` only after their corresponding stage
succeeds.

Run tests without network access:

```bash
python3 -m unittest discover -s experiments/public_html_capture_mvp/tests -v
```

When a page asks for login, verification, has no usable state, or does not
offer a directly downloadable media candidate, the run stops and reports that
limitation. It never falls back to the repository's CDP capture path.

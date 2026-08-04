# Public XHS Content Package Design

## Goal

Turn one publicly accessible Xiaohongshu note into a reusable local content
package while retaining the existing public-HTML-only safety boundary.

## Scope

The MVP supports video and image notes. It records normalized post facts,
downloads only complete media URLs exposed by the selected note object, saves
source evidence, and reports field-level availability. Video transcription
remains local. Image OCR, video keyframes, OCR, resumability, and archive
export are intentionally out of scope.

## Boundaries

- One user-provided URL per invocation.
- Ordinary HTTPS only: no browser automation, cookies, login, JavaScript
  execution, private endpoints, signatures, proxies, or comment collection.
- A value of zero, a missing public field, a failed operation, and an omitted
  processing step must be represented differently.
- A media-processing failure must not discard already captured page facts.

## Package Layout

```text
<run>/
  content_package.json
  report.md
  source/page.html
  source/initial_state.json
  source/media_candidates.json
  media/video.mp4                 # video notes only when exposed and downloaded
  media/cover.<ext>               # video cover or first image
  media/images/001.<ext> ...      # image notes
  derived/transcript.txt          # optional video post-processing
  derived/transcript_segments.json
  derived/subtitles.srt
```

## Data Model

`content_package.json` has schema version 2 and contains identity, post,
media, source evidence, processing results, limitations, and a `completeness`
map. Each completeness entry uses one of `available`, `zero`, `not_exposed`,
`failed`, `not_run`, or `intentionally_not_collected` and can include an
error reason.

Identity is based on the resolved note ID. The original URL and resolved URL
are preserved; a pre-existing package with the same ID can be recognised by
the CLI before starting a new run. The MVP reports the match but does not
overwrite an existing run.

## Media Rules

All images come from direct URLs found in `imageList`. The first selected image
is the cover for an image note. Video and image downloads are independent;
their candidate, selected URL, local filename, byte size, SHA-256, format and
dimensions are recorded. `faster-whisper` emits timestamped segments and SRT
when a video is available; its errors are recorded as post-processing failures.

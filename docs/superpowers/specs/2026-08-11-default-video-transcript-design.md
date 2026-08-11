# Default video transcript design

## Goal

Every newly captured video note should produce a local, timestamped transcript by default, because the downstream breakdown Skill requires it as video-input evidence. Image notes remain transcript-free.

## Command behavior

- `iwig capture` enables local transcription by default for a successfully downloaded video.
- `--no-transcribe` explicitly skips transcription.
- `iwig enrich --transcribe` remains available for resuming a skipped, failed, or older run.
- A cache hit for a completed video capture without a completed transcript reuses the local video and runs transcription; it never revisits the platform.

## State and failure contract

- A completed transcript sets `processing.transcribe.status` to `completed` and makes `readiness.transcript` ready.
- If video is unavailable, transcription is `not_run` and transcript readiness is unavailable.
- If local ASR is missing or fails, public capture remains completed while local processing is partial or failed. The result exposes the transcript failure through `readiness` and `active_errors`.
- A downstream breakdown Skill must require transcript readiness for video-note breakdown. It must reject or explicitly defer video packages without it, rather than infer spoken content from title, OCR, or frames.
- Image-note breakdown is not blocked by the absence of a transcript.

## User experience and dependencies

- `setup` continues to install `faster-whisper`; first video capture may download the configured local model and take longer.
- The default model and language remain `small` and `zh` on CPU int8.
- README and SKILL document that capture now includes ASR by default, the opt-out flag, outputs, and recovery command.

## Tests

- Default video capture forwards transcription to local processing.
- `--no-transcribe` prevents it.
- A cached video package missing a transcript resumes ASR without requesting the public page.
- An unavailable or failed ASR result leaves video breakdown readiness unavailable or failed while preserving capture facts.

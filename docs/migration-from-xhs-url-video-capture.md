# Migration from xhs-url-video-capture

The repository and sole public Skill are now named **IWIG**. New installs use `~/.iwig`; the legacy `~/.xhs-url-video-capture` directory is never moved or deleted automatically. Use `iwig.py enrich --run-dir` or an explicit output directory to read legacy runs, then validate and reindex them.

`schema_version: 2` remains temporarily for compatibility. New consumers must use `schema.name: iwig-content-package` and `schema.version: 2.0.0`.

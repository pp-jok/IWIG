# Public HTML validation record — 2026-08-04

This redacted record documents a local public-HTML-only validation. No browser, cookie, login, private API, signature, proxy, or comment endpoint was used.

- Note ID: `6a58be88000000000f02988f`
- Final package status: `completed`
- Available fields: title, description, tags, public author metadata, public counters, video, cover, local transcript and local keyframes.
- Candidate count: one directly exposed video candidate was selected.
- Video SHA-256: `b091872a30942a5bb8496e3630db2cc100ad5c1b25c886b187d77af29023a0d5`
- Observed duration: `303.1` seconds; H.264 video.
- Observed cover dimensions: `1080 × 1440`.
- Validation base commit: `a7600c8` (this record deliberately omits the share URL and all token-like query parameters).

Release-time revalidation of the same public link was attempted after the redirect hardening changes. The sandbox first blocked DNS; after a permitted retry the page and selected-note artifacts were retrieved, but the external runner stopped during the video stream and left a partial temporary file. That interrupted run is not reported as a successful capture. It does confirm that the new capture path never uses browser state or private endpoints; a full post-change media validation should be repeated in a stable network runner.

No user-provided public image-note URL was available for the image-note live validation. The image extraction path remains covered by unit tests; a corresponding redacted record should be added after such a URL is supplied.

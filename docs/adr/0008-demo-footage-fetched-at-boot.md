# 0008. Demo footage is downloaded and trimmed at first boot, not committed

**Status:** Accepted

## Context

The scenarios need about 280 MB of source video from Pexels and Roboflow's public examples.
Several clips start with a camera pan before settling into a fixed view, which would make a
fixed zone meaningless, and 4K sources waste decode time when the pipeline works at 960 px.

## Decision

`app/demo.py` declares each scenario as data: source URL, credit, trim window, zone, mode
and limit. On first start (or `python -m app.demo`) each clip is downloaded, trimmed to its
stable window, scaled to 960 px and written atomically to `CC_DEMO_VIDEO_DIR`. Its camera is
created only once its video is ready, so the wall fills in progressively and never shows a
"file not found" error.

## Consequences

- The repository and the deploy bundle stay small (about 1 MB), and nobody's footage is
  redistributed in the repo.
- The first boot depends on those URLs being reachable. A clip that fails to download is
  skipped and logged, and the other scenarios still start.
- The clips are re-encoded as MPEG-4 Part 2 (OpenCV's portable `mp4v`), which is larger than
  H.264 but decodes everywhere PyAV runs.

# 0001. One process, a thread per camera, one shared detector behind a lock

**Status:** Accepted

## Context

Each camera needs continuous decoding, inference and tracking, with results visible to the
API in under a second. Expected scale for a deployment: a handful to a few dozen cameras on
one machine, usually with one GPU. Frames are large (a 960×540 BGR frame is 1.5 MB), so any
boundary that serializes them is expensive.

Options considered:

1. **Process per camera** (multiprocessing or separate containers): isolates crashes, but
   each process loads its own model (about 0.5 GB of GPU memory each, more for RF-DETR), and
   frames or results must cross process boundaries.
2. **A queue between ingest and inference** (Redis, Kafka): scales out, but adds a broker to
   run and serializes every frame. It also queues by default, which is the wrong behaviour
   for live video.
3. **Threads in one process, one shared model:** PyTorch and the decoders release the GIL
   for the heavy work, frames stay in shared memory, and there is one model in GPU memory.

## Decision

Option 3. A `FrameReader` thread per camera keeps only the newest frame. A `CameraWorker`
thread per camera runs the pipeline. All workers share one detector, and calls are
serialized with a lock: neither Ultralytics nor RF-DETR guarantees thread-safe inference,
and on a single GPU, serial calls are about as fast as concurrent ones.

## Consequences

- One deployable, no broker, no serialization; the whole system runs on a laptop.
- Total throughput is capped by one accelerator: *cameras × FPS × inference time ≤ 1 s/s*.
  That's acceptable at this scale, with the cap tuned per deployment (`CC_MAX_FPS`,
  `CC_DETECTOR_IMGSZ`).
- One failure domain. Mitigated inside the process (every camera's errors are caught and
  retried), but a crash takes every camera down.
- The way out is in [architecture.md](../architecture.md#scaling-beyond-one-node): the same
  modules with the seams moved onto the network, and batched inference instead of a lock.

# Performance and capacity

Measured on an Apple M-series Mac (PyTorch on MPS) with the seven demo scenarios:

| Measurement | Value |
|---|---|
| YOLO26n inference, one 960×540 frame at `imgsz` 640 / 1280 | ~13–20 ms / ~30–40 ms |
| People found in the plaza scenario, `imgsz` 640 → 1280 (conf 0.25) | 5 → 52 |
| Processing rate, 7 cameras sharing the detector at `imgsz` 1280 | 3–6 FPS per camera |
| Full 960 px MJPEG at ~4.5 FPS | 266–1666 KB/s per camera (60–350 KB per frame; the cobblestone plaza is the worst) |
| Small 480 px tile stream at ~4.5 FPS | 92–443 KB/s per camera, **~3.5× less** |
| 8 concurrent API calls with the live wall open | 93 ms in total |

**Capacity model.** The shared detector is the bottleneck, and it is serialized, so the total
work is roughly *cameras × FPS × inference time ≤ 1 s per second*. With the Mac's ~35 ms at
1280, that's about 28 inferences per second, or 4 FPS each across 7 cameras, which matches
what was measured. A T4 runs YOLO26n at 1280 in an estimated 8–12 ms in FP32 PyTorch
(not measured here), so 80–120 inferences per second: 7 cameras at 11–15 FPS. Exporting the
model to TensorRT FP16 typically gives another 2–3×. The knobs, in order of leverage:
`ZW_DETECTOR_IMGSZ` (cost grows with the square of the size; 640 is enough except for distant
crowds), `ZW_MAX_FPS` (counting doesn't need 15 FPS; 5 is usually plenty), and the model size.

**Bandwidth model.** For each viewer, the wall costs the sum of the cameras' small-stream rates
at `ZW_STREAM_FPS`. For the demo at 8 FPS that's about 2 MB/s, or 7 GB per hour of viewing.
The enlarged view adds one full stream. Through CloudFront that's the dominant running cost
after the instance itself ([estimate](../aws/cost.md#cost-estimate)).

---

Part of the [system design](README.md) documentation.

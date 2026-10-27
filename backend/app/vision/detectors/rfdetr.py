import numpy as np
import supervision as sv

try:
    import rfdetr
except ImportError as e:  # pragma: no cover
    raise ImportError("The 'rfdetr' detector needs the rfdetr extra: uv sync --extra rfdetr") from e

_VARIANTS = {
    "nano": rfdetr.RFDETRNano,
    "small": rfdetr.RFDETRSmall,
    "medium": rfdetr.RFDETRMedium,
    "large": rfdetr.RFDETRLarge,
    "base": rfdetr.RFDETRBase,
}


class RFDETRDetector:
    """Roboflow RF-DETR (Apache-2.0). `model` is a variant name (nano/small/medium/large/base)."""

    name = "rfdetr"

    def __init__(self, model: str, confidence: float, device: str | None) -> None:
        try:
            cls = _VARIANTS[model.lower()]
        except KeyError:
            raise ValueError(
                f"Unknown RF-DETR variant {model!r}; use one of {list(_VARIANTS)}"
            ) from None
        self._model = cls(device=device) if device else cls()
        self._confidence = confidence

    def detect(self, frame_bgr: np.ndarray) -> sv.Detections:
        # RF-DETR expects RGB.
        detections = self._model.predict(frame_bgr[:, :, ::-1], threshold=self._confidence)
        class_names = detections.data.get("class_name")
        if class_names is None or len(detections) == 0:
            return detections[np.zeros(len(detections), dtype=bool)]
        return detections[class_names == "person"]

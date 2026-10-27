"""Zone counting on tracked detections. Pure logic with no I/O, so it is easy to test."""

from dataclasses import dataclass

import numpy as np
import supervision as sv

Polygon = list[tuple[float, float]]


@dataclass(frozen=True)
class ZoneResult:
    in_zone: np.ndarray  # bool mask over the detections passed in
    occupancy: int  # people currently inside the zone
    new_entries: int  # tracks that entered the zone for the first time this frame


class ZoneCounter:
    """Counts people whose feet (bottom-center of the box) are inside a polygon zone.

    `occupancy` is the per-frame count. Unique entries are counted per tracker id, so a
    person standing in the zone for minutes is counted once, not once per frame.
    """

    def __init__(self, zone: Polygon | None, forget_after_frames: int = 300) -> None:
        self._zone = zone
        self._forget_after = forget_after_frames
        self._polygon_zone: sv.PolygonZone | None = None
        self._polygon_wh: tuple[int, int] | None = None
        self._seen: dict[int, int] = {}  # tracker_id -> last frame index seen inside
        self._frame_index = 0
        self.unique_entries = 0

    def pixel_polygon(self, frame_wh: tuple[int, int]) -> np.ndarray | None:
        if self._zone is None:
            return None
        w, h = frame_wh
        return np.array([[round(x * w), round(y * h)] for x, y in self._zone], dtype=np.int64)

    def _zone_for(self, frame_wh: tuple[int, int]) -> sv.PolygonZone | None:
        if self._zone is None:
            return None
        if self._polygon_wh != frame_wh:
            self._polygon_zone = sv.PolygonZone(
                polygon=self.pixel_polygon(frame_wh),
                triggering_anchors=(sv.Position.BOTTOM_CENTER,),
            )
            self._polygon_wh = frame_wh
        return self._polygon_zone

    def update(self, detections: sv.Detections, frame_wh: tuple[int, int]) -> ZoneResult:
        self._frame_index += 1
        zone = self._zone_for(frame_wh)
        if len(detections) == 0:
            in_zone = np.zeros(0, dtype=bool)
        elif zone is None:
            in_zone = np.ones(len(detections), dtype=bool)
        else:
            in_zone = zone.trigger(detections)

        new_entries = 0
        if detections.tracker_id is not None:
            for tracker_id in detections.tracker_id[in_zone]:
                tid = int(tracker_id)
                if tid < 0:  # not yet a confirmed track
                    continue
                if tid not in self._seen:
                    new_entries += 1
                self._seen[tid] = self._frame_index

        # Tracks that have been gone this long can't come back with the same id.
        if self._frame_index % 100 == 0:
            cutoff = self._frame_index - self._forget_after
            self._seen = {t: f for t, f in self._seen.items() if f >= cutoff}

        self.unique_entries += new_entries
        return ZoneResult(in_zone=in_zone, occupancy=int(in_zone.sum()), new_entries=new_entries)

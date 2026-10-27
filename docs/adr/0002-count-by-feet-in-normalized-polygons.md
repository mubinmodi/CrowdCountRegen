# 0002. Count by foot position in normalized polygons; unique entries from tracker ids

**Status:** Accepted

## Context

v1 counted a person only when their whole bounding box was inside an axis-aligned rectangle
drawn in pixels. That misses anyone partly out of frame, can't follow a floor area seen in
perspective, and broke whenever the camera's resolution changed. It also counted people per
frame, so someone standing still for a minute counted 900 times.

## Decision

- Zones are polygons stored in normalized `[0, 1]` image coordinates and turned into pixels
  for each frame size.
- A person is in the zone when the **bottom-centre of their box** (their feet) is inside it,
  using supervision's `PolygonZone` with the `BOTTOM_CENTER` anchor.
- **ByteTrack** assigns ids. *Occupancy* is the count in the current frame; *entries* count
  each confirmed id once, the first time it is seen inside. Ids unseen for 300 frames are
  forgotten, so memory stays bounded.

## Consequences

- Zones follow floors and roads in perspective, survive resolution and sub-stream changes,
  and let overlapping cameras split an area without double counting.
- A danger zone needs no new counting code: it is the same zone with a different limit and
  drawing.
- An entry is per track, not per identity: someone who leaves and comes back counts again.
  Re-identification is out of scope.
- A foot point is 2D, so in low-angle shots a person just behind a zone can look inside it.

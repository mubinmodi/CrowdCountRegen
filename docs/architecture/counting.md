# Zones, tracking and counting

- **Normalized polygons.** Zones are stored in `[0, 1]` coordinates and turned into pixels per
  frame size, so they survive resolution changes and sub-stream switches.
- **Feet, not boxes.** A person counts when the bottom-centre of their box (where they stand) is
  inside the polygon. Requiring the whole box to be inside, as v1 did, misses anyone partly
  out of frame, and using the box centre counts people whose heads overlap an area.
- **Tracking.** ByteTrack gives each person a persistent id. Occupancy is per frame, but
  *entries* count each id once, the first time it's seen inside the zone. Ids unseen for 300
  frames are forgotten, so the memory used stays bounded.
- **One model, two meanings.** In occupancy mode entries are unique visitors. In danger-zone
  mode they are people who entered the zone, which the UI labels "Entered".

---

Part of the [system design](README.md) documentation.

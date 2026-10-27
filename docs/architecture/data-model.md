# Data model and storage

```mermaid
erDiagram
    users ||--o{ cameras : owns
    cameras ||--o{ count_samples : "per minute"
    cameras ||--o{ incidents : "alert periods"
    users {
        int id PK
        string email UK
        string password_hash "Argon2"
    }
    cameras {
        int id PK
        int owner_id FK
        string kind "stream|snapshot|webcam|file|browser"
        string source "never contains credentials"
        text password_enc "Fernet"
        json options
        json zone "normalized polygon, null = whole frame"
        int threshold
        string mode "occupancy|danger_zone"
        string scenario "demo key, nullable"
        string publish_token UK "browser cameras"
    }
    count_samples {
        int camera_id FK
        datetime minute "UTC, unique with camera_id"
        float avg_occupancy
        int peak_occupancy
        int entries
        int frames "weight for merging partial minutes"
    }
    incidents {
        int id PK
        int camera_id FK
        datetime started_at
        datetime ended_at "null while open"
        int peak
        int limit
        blob snapshot "annotated JPEG"
    }
```

- **Counts are aggregated in memory and written once a minute**, never per frame. Twenty
  cameras at 15 FPS is 300 frames a second but only 20 rows a minute. A restarted worker can
  write the same minute twice; rows merge, weighted by frame count.
- **Analytics** sums cameras per minute and then buckets the result (1 min to 6 h, picked
  from the range), so the combined view reports total people across cameras.
- **SQLite** in WAL mode by default (readers don't block the flusher), or Postgres with one
  setting. The schema is migrated with Alembic on startup.

---

Part of the [system design](README.md) documentation.

# Failure modes

| Failure | Effect | Handling |
|---|---|---|
| Camera unreachable, wrong password, wrong path | That camera only | Classified into `auth`, `not_found`, `unreachable`, `timeout` and others with a hint; reconnects with exponential backoff (2 s → 30 s); shown in the camera's stream health |
| Stream stalls without closing | Would freeze the worker | Read timeout (8 s), then reconnect. A worker never waits on a source for more than 1 s without checking for a stop |
| Decoder throws mid-stream | That camera, briefly | The reader closes the source, classifies the error and reconnects with backoff; `reconnects` goes up in stream health |
| Inference error (e.g. GPU out of memory) | One frame | Caught; the worker backs off 1 s and retries |
| Camera offline while alerting | Stale count | `over_limit` requires `state == running`, so an alert can't stick on a disconnected camera |
| Database error while recording (SQLite locked, a dropped Postgres connection) | That write | A failed count flush is logged, and those minutes are lost (counts are already drained from memory). The incident monitor handles each camera separately: an error is logged, the other cameras continue, and a failed close or peak update is retried on the next tick |
| Two writers store the same camera and minute at once | One minute's counts | The second insert hits the unique key; it rolls back and merges into the other's row instead |
| Schema upgrade on SQLite | Would cascade-delete counts and incidents when a table is rebuilt | Migrations run with foreign keys off and check integrity before committing |
| Process restart | In-memory counts for the current minute; open incidents | The minute in progress is flushed on clean shutdown. Open incidents are closed at their start time on the next boot |
| Slow browser | That viewer | Newest-frame-only sending: it gets fewer frames, never a growing buffer |
| Phone publisher disconnects or a second device takes over | That camera | Status shows `waiting` with a hint; the new device takes over the slot (generation counter) |
| Instance or host failure (AWS) | Everything | CloudWatch status-check alarms reboot it, or stop/start it onto new hardware ([details](../aws/README.md)) |

---

Part of the [system design](README.md) documentation.

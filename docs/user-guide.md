# User guide

A tour of the console: what each screen shows and what you can do on it. Setting up is in
[Getting started](getting-started.md).

## Live wall

The home page. Every camera's annotated video with its count, in a grid of 1–4 columns.

- **Header readouts:** people in all zones now (with the change over the last 60 s), unique
  visitors since start, cameras online, and active alerts (split into intrusions and
  over-limit cameras), plus a three-minute chart of the total.
- **Sections:** when both kinds exist, *Site safety* (danger zones) is shown above
  *Occupancy*.
- **Tiles:** the camera's state dot and name, the people in its zone, its limit, the people
  who entered or unique visitors, and the achieved frame rate.
  - **Occupancy cameras** draw the zone in orange and box people inside it in green. A meter
    fills towards the limit, and over it the tile pulses red with **OVER LIMIT**.
  - **Danger zones** have a barrier-tape border, draw the zone red with a striped edge, and
    box anyone inside it in red. An intrusion turns the tile red with **INTRUSION**.
- **Click a tile** to enlarge it: full-resolution video, the counts, its limit, a three-minute
  chart, the scenario's description, and links to edit its zone or see its history (incidents,
  for danger zones).

**Video paused?** To save bandwidth, video stops while the tab is in the background and
(where the server sets an idle timeout) after a while without input. A banner explains why
and offers **Resume video**. On a busy public deployment you may see *at its limit for live
video viewers*; video retries by itself. Counts and alerts keep updating either way
([how it works](architecture/live-video.md#pausing-and-capping-video)).

The top bar and the sidebar show the number of active alerts at all times.

## Cameras

The list of cameras with their state, source type (RTSP, HLS, SNAPSHOT, PHONE, …), zone,
current count against the limit, and frame rate. Danger zones are tagged **DANGER ZONE**.
Click one to edit it.

### Editing a camera

- **Name.**
- **Mode:**
  - *Occupancy* counts people in the zone and alerts above the **Alert limit**. Leave the
    limit empty for no alert.
  - *Danger zone* treats anyone inside as an intrusion. **People allowed inside** is
    usually 0; raise it if someone, such as a banksman, is meant to be there.
- **Video source:** the type and its settings, with **Test connection**
  ([Camera sources](camera-sources.md)).
- **Stream health:** state, the last error with a hint, resolution, codec, processing rate and
  reconnect count.
- **Zone:** drawn on a still frame from the camera. Click to add points, drag a point to move
  it, double-click a point to delete it, and clear it to count the whole frame. A person is
  inside when their feet are (the bottom-centre of their box), so a zone on the floor works
  even in perspective.

Changing the name or the limit applies immediately and keeps the counts. Changing the
source, zone or mode restarts the camera's processing, which restarts its unique-visitor
count ([why](adr/0003-alert-limits-outside-the-pipeline.md)).

### Phone and laptop cameras

A **Phone / browser** camera gets a **publish link** and a QR code once saved.

- Open the link on any device (no app), tap **Start camera** and allow camera access. The
  page shows what it's sending (frame rate and bitrate) and the live count from the server.
- On the device: **switch camera** (front/back), **quality** (640, 960 or 1280 px wide), and
  **frames per second** (5, 10 or 15). Keep the page open and the screen on while streaming.
- One device publishes at a time; a second one takes over.
- **Base URL** in the publish panel sets the address the QR code points to, for when devices
  reach the console at a different address than you do.
- **New link (revokes this one)** issues a new link, and anyone using the old one is
  disconnected. Treat the
  link like a password: whoever has it can stream to that camera.

## Incidents

Every period a camera spent over its limit, newest first, refreshed every few seconds.

- **Readouts:** incidents open now, incidents in the last hour, the longest one, and the
  camera with the most in the last hour.
- **Each row:** the annotated frame from when it started (click to enlarge), the camera, how
  many people were inside (danger zones) or the peak against the limit (occupancy), when it
  started, and its duration, which keeps counting while it's open.
- **Filter** by camera with the selector, or open *Incidents* from a danger zone's enlarged
  view.

An incident opens once a camera has been alerting for a second, so a single false detection
doesn't count. It closes after the camera has been clear for 3 s (danger zones) or 15 s
(occupancy). The newest 200 per camera are kept ([details](architecture/alerts-and-incidents.md)).

## Analytics

Counts recorded once a minute while cameras run, for **one camera or all combined**, over
**1 hour, 24 hours, 7 days or 30 days**:

- Peak occupancy (and when), average occupancy, unique visitors (zone entries), and coverage
  (how much of the range has data).
- **Occupancy** over time (average and peak), **Entries** per bucket, and **Busiest hours**
  (average occupancy by hour of day).

The combined view adds cameras up minute by minute, so it reports total people across
cameras. Its peak is an upper bound, since cameras may not have peaked at the same moment.

## Accounts

Sign up with an email and password. Every camera, count, incident and stream belongs to its
owner, and nobody else can see it.

## Demo mode

On a demo deployment there's no sign-in, and everyone shares one demo account.

- The live wall opens with a **welcome guide**: what the cameras show and five things to try
  (watch the wall, open a camera, check the incidents, change a rule, use your phone). Hide it
  with the arrow; it stays collapsed to a slim bar on your next visits, with **Show guide** to
  bring it back.
- The guide offers **Use my phone** (add a phone camera) and **Reset scenarios** (put every
  scenario's zone, mode and limit back).
- Only phone/browser cameras can be added, and the scenario cameras can be edited but not
  removed.

The scenarios and a five-minute walkthrough are in [the demo](demo.md).

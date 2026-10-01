# Couples Photo Quiz — MVP PRD

Last updated: 2026-09-25

## Overview

A two-player iOS game that finds trips a couple took together by matching photo time and location across both phones, then turns those photos into "when and where was this?" quizzes.

- **Problem:** Couples have thousands of shared photos but rarely revisit them. Existing apps (memu, Throwbacks, WhereWas, Camera Roll Trivia) either quiz one person on their own library or require picking photos by hand.
- **Differentiator:** Automatic trip discovery from two libraries, with no face recognition. Each partner is quizzed on photos the other one took.
- **MVP goals:** Accurate trip detection on real libraries. A playable daily loop for one couple. No raw photos or exact coordinates leave the phone, except quiz photos the sender approves.
- **Non-goals (MVP):** Android, family or group mode, face recognition, social feed.

## Target users and core loop

MVP users are couples where both partners use an iPhone and take photos when they travel. Long-distance couples are included, so pairing must work remotely.

1. Install, Sign in with Apple, grant photo library access.
2. Invite partner by link or QR code; partner joins.
3. Both phones index photo metadata locally; the app shows "You've taken N trips together."
4. Play a first round: 5 photos from one trip, guess where (map pin) and when.
5. Every day after that: one challenge from your partner, one back, streak kept.

## Pairing

Pair with Sign in with Apple plus an invite link or QR code, and sync through a CloudKit shared zone. Apps cannot read a user's iCloud account directly, so "use iCloud" in practice means these two pieces. Bluetooth is a P1 add-on; WeChat is P2.

| Method | How it works | Pros | Cons | Priority |
| --- | --- | --- | --- | --- |
| Sign in with Apple + invite link/QR | Stable user ID; partner opens link or scans code to join | Works remotely; no password | Apple users only | P0 |
| CloudKit shared zone (CKShare) | Both partners write hashed buckets and quiz data to one shared zone | No custom server; Apple handles auth and storage | Apple-only; CloudKit quotas | P0 (sync) |
| Bluetooth / nearby (MultipeerConnectivity) | Hold phones together to pair; can also exchange data fully offline | Fun in-person moment; strongest privacy | Both must be together; excludes long-distance couples | P1 |
| WeChat login | WeChat Open Platform SDK | Reaches China users; works on Android too | Developer account verification needed (confirm requirements); needs Android to matter | P2 |

## Trip detection

Match on time + GPS first. Use visual similarity only as a tiebreaker where GPS is missing, and let users confirm anything uncertain.

GPS is not actually less reliable than timestamps. Photos from your own iPhone camera usually carry both, as long as Camera has location permission. Photos saved from WeChat or other apps usually lose both: GPS is stripped and the creation date becomes the save date. Measure GPS coverage in the spike before building tier 2.

| Tier | Signal | Method | Confidence | Priority |
| --- | --- | --- | --- | --- |
| 1 | Time + GPS | Geohash-6 (~1 km) × 1-hour buckets, salted hashes, set intersection including neighbor cells | High | P0 |
| 2 | Time + visual similarity | Where time windows overlap but one side lacks GPS: on-device image embeddings (Vision feature prints or MobileCLIP), compared only within those windows | Medium; generic scenes (beaches, restaurant tables) cause false matches | P1 |
| 3 | User confirmation | "Were you two together Mar 3–7?" | Highest | P0 |

**Trip assembly:** Infer each partner's home (most frequent nighttime location) and work (most frequent weekday daytime location) over the last 90 days. Users confirm or edit both in the app, since iOS doesn't give apps the Home and Work places set in Maps. Draw a 5 km buffer around each partner's home–work commute. If the two homes are far apart, a spot outside either partner's buffer counts, so visiting each other counts; if they share a home, it must be outside both. A window counts as a trip when it is matched (tier 1–3) under this rule and has at least 5 photos across both devices. There is no minimum duration, so local dates count. Once a trip is confirmed, include both partners' photos from that window, even unmatched ones. This covers the common case where only one partner takes photos.

**Filters:** Drop screenshots, images without capture metadata, burst duplicates, and very dark or blurry shots.

## Quiz gameplay

Each round is 5 photos from one trip, preferring photos your partner took. Scoring values below are starting points to tune.

- **Where:** Drop a pin on a map. Full points within 1 km, decaying to zero at 500 km.
- **When:** Pick year, then month, then day; points for each level you get right.
- **Reveal:** After each guess, show the real spot on the map and the trip it came from.
- **Veto:** The photo's owner previews every photo before it is sent and can skip any of them.
- **Daily challenge:** Each partner sends one photo a day and answers one; both answering keeps the streak.

## Scope

P0 is only what the core loop needs; everything else waits until the loop is validated.

| Priority | Features |
| --- | --- |
| P0 | Sign in with Apple; invite link/QR pairing; photo library permission, including limited-access handling; local metadata index; tier 1 matching + tier 3 confirmation; trip list; quiz round (where + when); photo veto; daily challenge + streak; push notifications |
| P1 | Bluetooth tap-to-pair; tier 2 visual similarity; timed mode; shareable trip recap cards; home-screen widget |
| P2 | Family/group mode (matching subsets of members); "who took it?" and "who's missing?" modes; WeChat login; Android |

## Privacy and data

Only salted bucket hashes and owner-approved quiz photos ever leave the phone.

- **Stays on device:** Original photos, exact coordinates, raw timestamps, image embeddings (P1: exchanged only for candidate time windows).
- **Shared with partner:** Salted hashes of time-location buckets; approved quiz photos; scores. All stored in the pair's CloudKit shared zone.
- **Salt:** Generated at pairing and kept on the two devices. Bucket hashes are low-entropy, so anyone holding the salt could brute-force them; never store it server-side.
- **Unpairing:** Deletes the shared zone and all quiz photos in it.
- **No face recognition:** Avoids biometric-data rules such as Illinois BIPA.
- **App Store:** Clear photo-library purpose string and an accurate privacy label.

## Tech stack

No custom backend in the MVP: all logic runs on device, and CloudKit handles identity-linked storage and sync.

- **Spike (before any Swift):** Python + osxphotos to export capture time and GPS from both partners' Photos libraries; pandas + ST-DBSCAN to test matching and trip clustering.
- **App:** Swift / SwiftUI, PhotoKit, CoreLocation (reverse geocoding), MapKit (pin guessing); Vision / Core ML for tier 2 (P1).
- **Identity and sync:** Sign in with Apple; CloudKit shared zone (CKShare); CloudKit subscriptions for push.
- **Local storage:** SwiftData or SQLite for the metadata index and bucket hashes.

**Pipeline:** PhotoKit scan → local index → bucket + hash → upload hashes to the shared zone → each client intersects locally → trip clustering → user confirms → quiz generation.

## Metrics, milestones, risks

The first gate is trip-detection accuracy on your own two libraries; nothing else gets built until it passes.

**Success metrics**

- Trip detection: at least 90% precision against trips you label by hand (recall target to set after the spike).
- Activation: share of pairs that finish pairing and play a first round.
- Retention: day-7 daily-challenge completion; median streak length.

**Milestones**

| Weeks | Milestone | Gate |
| --- | --- | --- |
| 1–2 | Python spike on both libraries | Precision ≥ 90%; GPS coverage measured |
| 3–4 | Pairing, CloudKit sync, local indexing | Two real phones find the same trips |
| 5–6 | Quiz round, veto, daily challenge | One full week played by you two |
| 7 | TestFlight with 5–10 couples | Activation and day-7 numbers |

**Risks**

- Low GPS coverage in real libraries → pull tier 2 into P0.
- CloudKit quotas or CKShare friction → fall back to a small backend (e.g. Supabase) storing only hashes.
- App Review questions about photo access → keep processing on device and explain it in the purpose string.
- One partner on Android → out of scope for MVP; track how often testers hit it.

**Open questions**

- [x] Should local dates in your own city count, or only trips away from home?
  - Create a 5 km buffer around the commute (home–work); anywhere outside the buffer counts.
- [x] Minimum distance and duration that define a trip.
  - Distance: as above.
  - Duration: no minimum; a trip needs at least 5 photos in total across both devices.
- [x] Monetization: free, one-time unlock, or subscription.
  - Free first.
- [x] Whose buffer applies?
  - Different homes: outside either partner's buffer counts, so visits count. Shared home: must be outside both.

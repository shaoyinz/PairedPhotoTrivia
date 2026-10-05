# Couples Photo Quiz — MVP PRD

Last updated: 2026-10-04

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

**Trip assembly:** Infer each partner's home (most frequent nighttime location) and work (most frequent weekday daytime location) over the last 90 days. Users confirm or edit both in the app, since iOS doesn't give apps the Home and Work places set in Maps. Editing is one search field that takes a zip code, a city or an address, then a pin they can drag; it only needs to land within a km or two. The app asks for the current home only. Draw a 5 km buffer around each partner's home–work commute. If the two homes are far apart, a spot outside either partner's buffer counts, so visiting each other counts; if they share a home, it must be outside both. A window counts as a trip when it is matched (tier 1–3) under this rule and has at least 5 photos across both devices. There is no minimum duration, so local dates count. A trip away from home continues across nights until either partner is seen back in their home city (about 25 km around home and work), so a multi-day trip stays one trip even when nobody takes photos overnight. Once a trip is confirmed, include both partners' photos from that window, even unmatched ones. This covers the common case where only one partner takes photos. When one partner stops shooting partway through, the trip's ends carry on along the other's photos outside their own home city, as long as those photos are never more than 24 hours apart, until either partner is seen back home.

**Past homes and old-home days:** The app never asks where you used to live. It infers past homes from where each partner's evening and night photos cluster across the whole library, and judges every photo against the home that partner had when it was taken, so a trip taken while living somewhere else is measured from that home. Everyday moments at a home you have since left are not excluded: they hold memories too. They become old-home days, each at most about a day and never joined across nights, under the same ≥ 5 photo rule. Old-home days are quiz material, but rounds come mostly from trips.

**Filters:** Drop screenshots, images without capture metadata, burst duplicates, and very dark or blurry shots.

## Quiz gameplay

Each round is 5 photos from one trip, preferring photos your partner took; now and then a round comes from an old-home day instead. Scoring values below are starting points to tune.

- **Where:** Drop a pin on a map. Full points within 1 km, decaying to zero at 500 km.
- **When:** Pick year, then month, then day; points for each level you get right.
- **Reveal:** After each guess, show the real spot on the map and the trip it came from.
- **Veto:** The photo's owner previews every photo before it is sent and can skip any of them.
- **Daily challenge:** Each partner sends one photo a day and answers one; both answering keeps the streak.

## Memory journal

After a quiz photo is revealed, each partner can attach a short note about that moment. Entries stay on the author's phone unless the author shares them, so the journal is a private diary first and a shared scrapbook only by choice. This is P1: it deepens the loop but isn't needed to validate it.

- **When:** The reveal screen offers "Add a memory?" after each guess, and it can be skipped. Entries can also be added or edited later from any quiz photo in the trip view.
- **Who:** One entry per partner per photo; each partner can edit or delete only their own.
- **Local by default:** A new entry is saved only on the author's phone. Each entry has a "Share with partner" switch, off by default, and only shared entries sync. Turning the switch off later deletes the shared copy.
- **Sender's note:** The sender can write theirs while approving the photo. If shared, it stays hidden until the guess is in, since a note could give away the answer.
- **Blind reveal:** You see your partner's shared entry only after you write your own (shared or not) or skip. Finding out whether you remember the moment the same way is part of the game.
- **Content:** Plain text, up to 500 characters. Voice notes are P2.
- **Memory book:** The trip view lists its quiz photos in time order, with your entries and your partner's shared entries beside each one.
- **Nudge:** When your partner shares an entry, a push invites you to add yours to unlock it. Journaling never affects the streak, so the daily challenge stays quick.
- **Storage:** Every entry lives in the local store. A shared entry is also written as one CloudKit record in the pair's shared zone, linked to its quiz photo.

## Scope

P0 is only what the core loop needs; everything else waits until the loop is validated.

| Priority | Features |
| --- | --- |
| P0 | Sign in with Apple; invite link/QR pairing; photo library permission, including limited-access handling; local metadata index; tier 1 matching + tier 3 confirmation; trip list; quiz round (where + when); photo veto; daily challenge + streak; push notifications |
| P1 | Bluetooth tap-to-pair; tier 2 visual similarity; timed mode; shareable trip recap cards; home-screen widget; memory journal (text) |
| P2 | Family/group mode (matching subsets of members); "who took it?" and "who's missing?" modes; WeChat login; Android; memory journal voice notes |

## Privacy and data

Only salted bucket hashes, owner-approved quiz photos, and memory journal entries the author chooses to share ever leave the phone.

- **Stays on device:** Original photos, exact coordinates, raw timestamps, home and work (current and inferred past homes), image embeddings (P1: exchanged only for candidate time windows), unshared memory journal entries.
- **Shared with partner:** Salted hashes of time-location buckets; approved quiz photos; memory journal entries the author shares (P1); scores. All stored in the pair's CloudKit shared zone.
- **Salt:** Generated at pairing and kept on the two devices. Bucket hashes are low-entropy, so anyone holding the salt could brute-force them; never store it server-side.
- **Unpairing:** Deletes the shared zone, with all quiz photos and shared journal entries in it. Each partner keeps their own entries locally; entries on the other partner's photos keep only their text.
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
- Memory journal (P1): share of revealed quiz photos with an entry; share of entries shared with the partner.

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
- [x] Should memory journal entries sync to the partner?
  - Local by default. The author can share any entry, and only shared entries sync.
- [x] What if only one partner takes photos for part of a trip?
  - A trip needs at least one match. From there its ends carry on along the other partner's photos outside their own home city, each within 24 hours of the last, until either partner is seen back home. If one partner went home without taking a photo there, the other's days alone still count; the owner's photo approval is the backstop.
- [x] What about places you used to live?
  - Only the current home is asked for. Past homes are inferred, and everyday moments there become old-home days for the quiz, rather than trips or exclusions.

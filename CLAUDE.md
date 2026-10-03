# Couples Photo Quiz

Two-player iOS game. It finds trips a couple took together by matching photo time + location across both partners' libraries, then quizzes each partner on "when and where was this?" Full spec: `docs/PRD.md`.

## Current phase

Phase 1: Python spike (weeks 1–2). Algorithm in Python; the only Swift is a throwaway iOS
metadata exporter (`ios/MetadataExport/`), since this Mac's Photos library is not iCloud-synced
and a remote partner may have no Mac. See `docs/IMPLEMENTATION_PLAN.md`.
- Goal: validate trip detection on two real Photos libraries.
- Gate: ≥ 90% precision against hand-labeled trips; report GPS coverage (% of photos with location).

## Key decisions (ask before changing)

- No face recognition. "Together" = overlapping time + location across both libraries.
- Matching: geohash-6 (~1 km) × 1-hour buckets, salted hashes (e.g. HMAC-SHA256), set intersection that includes neighbor cells.
- Home = most frequent nighttime location; work = most frequent weekday daytime location (last 90 days). User can confirm or edit.
- 5 km buffer around each partner's home–work commute (start with a buffer around the straight home→work segment).
  - Different homes: a spot outside either partner's buffer counts (visits count).
  - Shared home: a spot must be outside both buffers.
- Trip = matched window under the buffer rule with ≥ 5 photos across both devices. No minimum duration.
- A trip spans nights until either partner is seen back in their home city (25 km around home–work), or 72 h pass without a located photo. Pausing photos alone does not end it.
- After a trip is confirmed, include both partners' photos in that window, even unmatched ones.
- Filter out screenshots, images without capture metadata, and burst duplicates.
- Times in UTC; distances in km.
- MVP: iOS-only, free, no custom backend (Sign in with Apple + CloudKit shared zone).

## Privacy (hard constraints)

- Only salted bucket hashes, owner-approved quiz photos, and memory journal entries the author chooses to share may leave a device. Never upload original photos, exact coordinates, or raw timestamps.
- The salt lives only on the two paired devices.
- Spike data stays local: exports go in `data/` (gitignored). Never commit real coordinates, timestamps, or photo exports.

## Repo layout (planned)

- `docs/PRD.md`: product spec
- `docs/IMPLEMENTATION_PLAN.md`: phase framing, gates, risks — the entry point
- `docs/plan/1.N-*.md`: one file per executable phase-1 step
- `spike/`: Python trip-detection spike
- `data/`: local metadata exports (gitignored)
- `ios/`: SwiftUI app (phase 2+)

## Spike stack

- Metadata export: primary path is the iOS exporter (PhotoKit → CSV, each partner on their own iPhone); osxphotos is the alternative where a Mac library is actually synced. Both emit the same CSV schema.
- Python 3.11+ (pin 3.12; system Python is 3.14), pandas, scikit-learn (ST-DBSCAN or DBSCAN on space + time), a geohash library, shapely for buffers.
- Commands: TBD once `spike/` exists.

## Conventions

- Keep the core matching and clustering logic in plain, pure functions with tests. It will be ported to Swift, so avoid pandas-only tricks inside the algorithm.
- Git: commit straight to `main`, with no feature branches or PRs, until the app ships as a product. Revisit this before release.

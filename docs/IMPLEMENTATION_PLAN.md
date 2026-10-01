# Implementation Plan

Derived from `docs/PRD.md`. Last updated: 2026-10-01.

Phase 1 (the Python spike) is specified in detail because it is the current phase and the
first gate. Phases 2–4 are sequenced and scoped, but deliberately left coarser: the spike's
numbers change what gets built (tier 2 in particular).

Guiding constraint for every phase: the matching and clustering core is written as pure
functions over plain data, because it gets ported to Swift. No pandas inside the algorithm —
pandas only at the I/O and reporting edges.

---

## Phase 1 — Python spike (weeks 1–2)

**Goal:** validate trip detection on two real Photos libraries.
**Gate:** ≥ 90% precision against hand-labeled trips; GPS coverage measured and reported.

**Deviation from `CLAUDE.md`, accepted deliberately:** phase 1 now contains a small amount of
Swift — a throwaway iOS metadata exporter ([§1.2a](plan/1.2-export.md)) — because osxphotos needs a Mac Photos
library that is actually synced, and a partner on a long-distance pair may have no Mac at all.
The exporter's `PHAsset` enumeration is lifted into the phase 2 indexer, so it is prototype,
not detour. The matching and clustering core stays in Python for this phase.

### Phase 1 steps

Each step is its own file under `docs/plan/`, so a step can be worked on, reviewed, and checked
off without scrolling past the other eight. This document keeps the framing and the gate.

| Step | What it settles |
| --- | --- |
| [1.1 Scaffold](plan/1.1-scaffold.md) | Repo, uv project, module contracts, synthetic walking skeleton |
| [1.2 Export](plan/1.2-export.md) | iOS exporter (primary), osxphotos (alternative), one CSV schema |
| [1.3 Filters](plan/1.3-filters.md) | Screenshots, missing metadata, burst dupes — each countable |
| [1.4 Buckets and matching](plan/1.4-buckets-and-matching.md) | geohash6 × hour, salted hashes, one-sided expansion |
| [1.5 Anchors](plan/1.5-anchors.md) | Home and work inference from local hours |
| [1.6 Away rule](plan/1.6-away-rule.md) | Commute buffer and what counts as away |
| [1.7 Trip assembly](plan/1.7-trip-assembly.md) | Sessionization, ≥ 5 photos, backfill |
| [1.8 Labels and evaluation](plan/1.8-evaluation.md) | Precision, recall, split/merge, GPS coverage, sweep |
| [1.9 Tests](plan/1.9-tests.md) | Unit tests and the vectors the Swift port reuses |

### Gate review

Precision ≥ 90% → proceed to phase 2. GPS coverage low (say < 60% of travel photos) → tier 2
visual similarity moves into P0 and phase 2 grows by roughly a week. Record the decision in
the report.

---

## Phase 2 — Pairing, sync, local indexing (weeks 3–4)

**Gate:** two real phones independently find the same trips.

- [ ] `ios/` SwiftUI app skeleton; Sign in with Apple; photo-library permission with an
      explicit limited-access path (PRD lists it as P0)
- [ ] Port the pure spike modules to Swift structs, driven by `tests/vectors/*.json` — same
      inputs, same outputs, in XCTest
- [ ] PhotoKit incremental index into SwiftData: uuid, UTC timestamp, tz offset, coordinates,
      filter flags. Lift the `PHAsset` enumeration from `ios/MetadataExport/` ([§1.2a](plan/1.2-export.md)) — it is
      already proven against a real library at full size. Full first pass with progress UI,
      then `PHPhotoLibraryChangeObserver`
- [ ] Carry over whatever the exporter learned about `.limited` authorization
- [ ] Invite link + QR pairing; CloudKit shared zone (CKShare) for hashed buckets and scores
- [ ] **Salt exchange:** carry the salt in the QR / invite payload so it never reaches
      CloudKit. Verify whether CKRecord `encryptedValues` in a shared zone is genuinely
      server-opaque before considering the simpler route; until verified, the QR payload wins
- [ ] Upload own expanded+salted buckets, download partner's, intersect locally, cluster,
      show the trip list with a tier-3 "were you two together?" confirm step
- [ ] Home/work confirm-and-edit screen
- [ ] Two-phone check: same trip list on both devices, no coordinates or raw timestamps in the
      CloudKit dashboard (inspect it and confirm)

## Phase 3 — Quiz loop (weeks 5–6)

**Gate:** one full week played by the two of you.

- [ ] Round generation: 5 photos from one trip, preferring the partner's photos
- [ ] Veto screen — owner previews and skips before anything uploads; upload only on approve
- [ ] Where: MapKit pin guess, full points ≤ 1 km decaying to zero at 500 km
- [ ] When: year → month → day, points per level
- [ ] Reveal: real location on the map plus the trip it came from
- [ ] Daily challenge, streak, CloudKit subscription push notifications
- [ ] Unpair: deletes the shared zone and every quiz photo in it
- [ ] Scoring constants in one file — they are explicitly tuning targets

## Phase 4 — TestFlight (week 7)

- [ ] Photo-library purpose string and privacy label matching actual behavior
- [ ] Onboarding that states the privacy model in a sentence
- [ ] 5–10 couples; instrument activation (pairing → first round) and day-7 challenge
      completion; count how often a tester's partner is on Android

---

## Risks and the trigger for each

| Risk | Trigger | Response |
| --- | --- | --- |
| Low GPS coverage | Phase 1 coverage report | Pull tier 2 (Vision feature prints) into P0 |
| Trips merge or split badly | Split/merge counts at the gate | Swap sessionization for DBSCAN on space × time |
| CKShare friction or quotas | Phase 2 two-phone test | Minimal backend (e.g. Supabase) holding only hashes |
| App Review on photo access | Submission | On-device processing, explained in the purpose string |
| Anchor inference wrong | Phase 1 anchors output | Confirm/edit UI is already P0; keep it prominent |

## Open items for the plan itself

- [ ] Confirm gap-based sessionization over ST-DBSCAN as the phase-1 default (PRD names
      ST-DBSCAN; the reasoning is in [1.7](plan/1.7-trip-assembly.md) and the sweep will settle it)
- [ ] How the remote partner gets the exporter: TestFlight, or an Xcode build on their own Mac.
      TestFlight means a paid developer account is needed in phase 1 rather than phase 4
- [ ] Partner's export should not travel as raw rows: have them run ingest → buckets →
      coverage report locally and send only salted hashes plus aggregate stats. Matching needs
      nothing more, and it tests the privacy model instead of bypassing it
- [ ] Dark/blurry filtering needs pixel access; deferred to phase 2, not dropped

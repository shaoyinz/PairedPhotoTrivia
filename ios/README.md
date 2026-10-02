# ios/

## `MetadataExport/` — throwaway PhotoKit → CSV exporter ([§1.2a](../docs/plan/1.2-export.md))

One screen: grant Photos access, tap **Export metadata**, then share the CSV (AirDrop it to the
Mac). It reads metadata only — never image data — so photos stored only in iCloud export too.
The phase 2 indexer lifts its `PHAsset` enumeration (`Exporter.swift`).

Requires Xcode 27 (installed 2026-10-01: Xcode 27.0, iOS 27.0 SDK). Runs on iOS 16+.

### Run it on an iPhone (free personal team, expires after 7 days)

1. `open ios/MetadataExport/MetadataExport.xcodeproj`
2. Target **MetadataExport** → *Signing & Capabilities* → pick your team. If Xcode says the
   bundle ID is taken (each personal team needs its own), change
   `com.shaoyinz.photoquiz.MetadataExport` to anything unique.
3. Plug in the iPhone, select it as the run destination, ⌘R. First launch on the phone:
   *Settings → General → VPN & Device Management* → trust the developer.
4. In the app: **Allow access to Photos** → choose **Allow Full Access**, then **Export
   metadata** → **Share** → AirDrop to the Mac.
5. On the Mac, from `spike/`:
   `uv run photoquiz ingest -p a --csv ~/Downloads/photo_metadata_<stamp>.csv`

Build check (still open in §1.2a): the row count on the finished screen should match the photo
count at the bottom of the Photos app's library view, and "Time zone differs from this phone's"
should be roughly the photos taken while traveling, not the total row count.

Compile-only check without a device:

```bash
xcodebuild -project ios/MetadataExport/MetadataExport.xcodeproj -scheme MetadataExport \
  -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build
```

### What it writes

The CSV header comes from `CSVRow.header`, copied byte for byte from `CSV_HEADER` in
`spike/src/photoquiz/schema.py`; `spike/tests/test_schema.py` checks both against one pinned
string. Two columns differ from the osxphotos path (§1.2b):

- `tz_offset_s` comes from PHAsset's **private** `localCreationDate`, since PhotoKit has no public
  per-asset time zone. When that is missing, the phone's time zone is used, and the screen counts
  how often. Fine for a sideload; it cannot ship in the App Store app.
- `camera_make` / `camera_model` are always empty: they live only in EXIF, which needs image data.

The file holds exact coordinates and timestamps: it goes into `data/` (gitignored) and nowhere else.

# ios/

Placeholder. Nothing here builds yet.

`MetadataExport/` (the throwaway PhotoKit → CSV exporter, [§1.2a](../docs/plan/1.2-export.md))
lands here. Its prerequisite is met:

- **Full Xcode** (not just the Command Line Tools at `/Library/Developer/CommandLineTools`),
  with an iOS SDK and a device-capable toolchain. Installed as of 2026-10-01: Xcode 27.0
  (27A266a) with the iOS 27.0 SDK at `/Applications/Xcode-27.0.0.app`. §1.2a is unblocked.

The exporter writes its CSV header from a constant copied verbatim from `CSV_HEADER` in
`spike/src/photoquiz/schema.py`; `spike/tests/test_schema.py` pins that string.

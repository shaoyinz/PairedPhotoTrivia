# ios/

Placeholder. Nothing here builds yet.

`MetadataExport/` (the throwaway PhotoKit → CSV exporter, [§1.2a](../docs/plan/1.2-export.md))
lands here once its prerequisite exists:

- **Full Xcode** (not just the Command Line Tools at `/Library/Developer/CommandLineTools`),
  with an iOS SDK and a device-capable toolchain. As of 2026-10-01 only the CLT is installed,
  so §1.2a is blocked on the Xcode install.

The exporter writes its CSV header from a constant copied verbatim from `CSV_HEADER` in
`spike/src/photoquiz/schema.py`; `spike/tests/test_schema.py` pins that string.

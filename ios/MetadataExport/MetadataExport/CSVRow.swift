import Foundation

/// One row of the export CSV: the contract with `spike/src/photoquiz/schema.py`.
///
/// `header` is copied byte for byte from `CSV_HEADER`, and `spike/tests/test_schema.py` reads it
/// out of this file, so changing one side without the other fails a test.
struct CSVRow {
    static let header = "asset_id,utc_epoch,tz_offset_s,lat,lon,is_screenshot,burst_id,is_burst_pick,camera_make,camera_model,width,height"

    var assetID: String
    var utcEpoch: Int?
    var tzOffsetS: Int?
    var lat: Double?
    var lon: Double?
    var isScreenshot: Bool
    var burstID: String?
    var isBurstPick: Bool
    var cameraMake: String?
    var cameraModel: String?
    var width: Int?
    var height: Int?

    /// No line terminator. Same encoding as `schema.format_row`: empty cell = missing,
    /// booleans 0/1, coordinates to 6 decimals.
    var line: String {
        [
            Self.field(assetID),
            utcEpoch.map(String.init) ?? "",
            tzOffsetS.map(String.init) ?? "",
            lat.map { String(format: "%.6f", $0) } ?? "",
            lon.map { String(format: "%.6f", $0) } ?? "",
            isScreenshot ? "1" : "0",
            Self.field(burstID),
            isBurstPick ? "1" : "0",
            Self.field(cameraMake),
            Self.field(cameraModel),
            width.map(String.init) ?? "",
            height.map(String.init) ?? "",
        ].joined(separator: ",")
    }

    /// RFC 4180, as Python's `csv` reads it: quote a field holding a comma, quote or newline.
    static func field(_ s: String?) -> String {
        guard let s else { return "" }
        // Scalars, not Characters: "\r\n" is one Character and would match neither.
        guard s.unicodeScalars.contains(where: { $0 == "," || $0 == "\"" || $0 == "\n" || $0 == "\r" }) else { return s }
        return "\"" + s.replacingOccurrences(of: "\"", with: "\"\"") + "\""
    }
}

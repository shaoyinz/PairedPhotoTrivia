import CoreLocation
import Foundation
import Photos

/// What the screen shows after a run. Plain values, so it crosses from the export task to the UI.
struct ExportResult: Sendable {
    let file: URL
    let rows: Int
    let noDate: Int
    let noGPS: Int
    /// The photo's own time zone was unreadable, so this phone's was written instead.
    let tzFromPhone: Int
    /// The photo's time zone differs from this phone's at that instant (mostly travel). It
    /// measures how wrong phase 2 would be if it used the phone's time zone, the only public option.
    let tzNotPhone: Int
    let limited: Bool
}

/// Metadata only: never requests image data, so photos that live only in iCloud export too.
enum Exporter {
    private static let chunk = 500

    static func run(limited: Bool, progress: (_ done: Int, _ total: Int) -> Void) throws -> ExportResult {
        let options = PHFetchOptions()
        // User library only: shared albums hold other people's photos, which would fake "together".
        options.includeAssetSourceTypes = [.typeUserLibrary, .typeiTunesSynced]
        // Defaults kept on purpose: no hidden assets and one asset per burst, which is what Photos
        // itself counts, so the row count can be checked against the Photos app. No sorting.
        let assets = PHAsset.fetchAssets(with: .image, options: options)
        let total = assets.count

        let file = FileManager.default.temporaryDirectory.appendingPathComponent(fileName(limited: limited))
        guard FileManager.default.createFile(atPath: file.path, contents: Data((CSVRow.header + "\n").utf8)) else {
            throw CocoaError(.fileWriteUnknown, userInfo: [NSFilePathErrorKey: file.path])
        }
        let out = try FileHandle(forWritingTo: file)
        defer { try? out.close() }
        try out.seekToEnd()

        let phone = TimeZone.current
        var tally = Tally()
        var done = 0
        progress(0, total)
        while done < total {
            let end = min(done + chunk, total)
            let lines = autoreleasepool {
                var s = ""
                for i in done..<end {
                    s += row(assets.object(at: i), phone: phone, tally: &tally).line + "\n"
                }
                return s
            }
            try out.write(contentsOf: Data(lines.utf8))
            done = end
            progress(done, total)
        }
        return ExportResult(
            file: file, rows: total, noDate: tally.noDate, noGPS: tally.noGPS,
            tzFromPhone: tally.tzFromPhone, tzNotPhone: tally.tzNotPhone, limited: limited
        )
    }

    private struct Tally {
        var noDate = 0
        var noGPS = 0
        var tzFromPhone = 0
        var tzNotPhone = 0
    }

    private static func row(_ asset: PHAsset, phone: TimeZone, tally: inout Tally) -> CSVRow {
        let created = asset.creationDate
        var tz: Int?
        if let created {
            let phoneOffset = phone.secondsFromGMT(for: created)
            if let own = ownOffset(asset, created: created) {
                tz = own
                if own != phoneOffset { tally.tzNotPhone += 1 }
            } else {
                tz = phoneOffset
                tally.tzFromPhone += 1
            }
        } else {
            tally.noDate += 1
        }
        let gps = asset.location.map(\.coordinate).flatMap { CLLocationCoordinate2DIsValid($0) ? $0 : nil }
        if gps == nil { tally.noGPS += 1 }
        return CSVRow(
            assetID: asset.localIdentifier,
            utcEpoch: created.map { Int($0.timeIntervalSince1970.rounded(.down)) },
            tzOffsetS: tz,
            lat: gps?.latitude,
            lon: gps?.longitude,
            isScreenshot: asset.mediaSubtypes.contains(.photoScreenshot),
            burstID: asset.burstIdentifier,
            isBurstPick: asset.representsBurst,
            // Make/model live only in the image's EXIF, which means fetching image data (and
            // downloading iCloud-only originals). Left empty: unknown, not "imported".
            cameraMake: nil,
            cameraModel: nil,
            width: asset.pixelWidth,
            height: asset.pixelHeight
        )
    }

    /// PhotoKit has no public per-asset time zone (checked against the iOS 27 SDK). PHAsset's
    /// private `localCreationDate` is the capture instant shifted by the photo's own offset, so the
    /// difference is that offset. Fine for a sideloaded throwaway; phase 2 cannot ship it.
    private static let hasLocalCreationDate = PHAsset.instancesRespond(to: NSSelectorFromString("localCreationDate"))

    private static func ownOffset(_ asset: PHAsset, created: Date) -> Int? {
        guard hasLocalCreationDate, let local = asset.value(forKey: "localCreationDate") as? Date else { return nil }
        let offset = Int(local.timeIntervalSince(created).rounded())
        // Real offsets are whole quarter hours within ±14 h. Anything else means the property does
        // not mean what we think, and the phone's time zone is the safer answer.
        guard abs(offset) <= 14 * 3600, offset % 900 == 0 else { return nil }
        return offset
    }

    private static func fileName(limited: Bool) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.dateFormat = "yyyyMMdd-HHmm"
        // A limited export must not pass for a full one once it is on the Mac.
        return "photo_metadata_\(f.string(from: Date()))\(limited ? "_LIMITED" : "").csv"
    }
}

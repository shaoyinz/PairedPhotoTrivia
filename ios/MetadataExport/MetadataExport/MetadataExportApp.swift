import Photos
import SwiftUI

/// Throwaway phase-1 exporter (docs/plan/1.2-export.md §1.2a): one screen, one button, one share sheet.
@main
struct MetadataExportApp: App {
    var body: some Scene {
        WindowGroup { ContentView() }
    }
}

@MainActor
final class ExportModel: ObservableObject {
    enum Phase {
        case idle
        case exporting(done: Int, total: Int)
        case finished(ExportResult)
        case failed(String)
    }

    @Published private(set) var access = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    @Published private(set) var phase = Phase.idle

    var isExporting: Bool {
        if case .exporting = phase { return true }
        return false
    }

    /// Access can change in Settings while the app is in the background.
    func refreshAccess() {
        access = PHPhotoLibrary.authorizationStatus(for: .readWrite)
    }

    func requestAccess() async {
        access = await PHPhotoLibrary.requestAuthorization(for: .readWrite)
    }

    func export() async {
        let limited = access == .limited
        phase = .exporting(done: 0, total: 0)
        UIApplication.shared.isIdleTimerDisabled = true  // a locked phone suspends the export
        defer { UIApplication.shared.isIdleTimerDisabled = false }
        do {
            let result = try await Task.detached(priority: .userInitiated) {
                try Exporter.run(limited: limited) { done, total in
                    Task { @MainActor in
                        // A late progress hop must not overwrite the finished state.
                        if self.isExporting { self.phase = .exporting(done: done, total: total) }
                    }
                }
            }.value
            phase = .finished(result)
        } catch {
            phase = .failed(error.localizedDescription)
        }
    }
}

struct ContentView: View {
    @StateObject private var model = ExportModel()
    @Environment(\.openURL) private var openURL

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Writes each photo's date, time zone and location to a CSV for the trip-detection spike. Only metadata is read, never the images. The file stays on this phone until you share it.")
                        .font(.callout)
                }
                Section("Photos access") { accessRows }
                if model.access == .authorized || model.access == .limited {
                    Section("Export") { exportRows }
                }
            }
            .navigationTitle("Metadata Export")
        }
        .onReceive(NotificationCenter.default.publisher(for: UIApplication.willEnterForegroundNotification)) { _ in
            model.refreshAccess()
        }
    }

    @ViewBuilder private var accessRows: some View {
        switch model.access {
        case .notDetermined:
            Button("Allow access to Photos") { Task { await model.requestAccess() } }
        case .authorized:
            Label("Full access", systemImage: "checkmark.circle")
        case .limited:
            Label("Limited access: only the photos you picked are visible, so GPS coverage and trip counts from this export would be meaningless.", systemImage: "exclamationmark.triangle")
                .foregroundStyle(.orange)
            settingsButton("Choose Full Access in Settings")
        default:  // .denied, .restricted
            Label("Photos access is off.", systemImage: "xmark.circle")
            settingsButton("Turn on Full Access in Settings")
        }
    }

    @ViewBuilder private var exportRows: some View {
        Button(model.access == .limited ? "Export selected photos only" : "Export metadata") {
            Task { await model.export() }
        }
        .disabled(model.isExporting)

        switch model.phase {
        case .idle:
            EmptyView()
        case let .exporting(done, total):
            ProgressView(value: Double(done), total: Double(max(total, 1))) {
                Text("\(done.formatted()) of \(total.formatted()) photos")
            }
        case let .finished(r):
            summary(r)
            ShareLink(item: r.file) {
                Label("Share \(r.file.lastPathComponent)", systemImage: "square.and.arrow.up")
            }
        case let .failed(message):
            Label(message, systemImage: "xmark.octagon").foregroundStyle(.red)
        }
    }

    private func summary(_ r: ExportResult) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("\(r.rows.formatted()) photos\(r.limited ? " (limited selection)" : "")").font(.headline)
            Text("With GPS: \((r.rows - r.noGPS).formatted()) (\(percent(r.rows - r.noGPS, of: r.rows)))")
            Text("No capture date: \(r.noDate.formatted())")
            Text("Time zone differs from this phone's: \(r.tzNotPhone.formatted())")
            if r.tzFromPhone > 0 {
                Text("Time zone unreadable, used this phone's: \(r.tzFromPhone.formatted())").foregroundStyle(.orange)
            }
        }
        .font(.callout)
    }

    private func settingsButton(_ title: String) -> some View {
        Button(title) {
            if let url = URL(string: UIApplication.openSettingsURLString) { openURL(url) }
        }
    }

    private func percent(_ n: Int, of total: Int) -> String {
        total == 0 ? "–" : (Double(n) / Double(total)).formatted(.percent.precision(.fractionLength(1)))
    }
}

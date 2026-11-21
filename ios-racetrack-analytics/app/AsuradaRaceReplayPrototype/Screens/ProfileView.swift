import SwiftUI

struct ProfileView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        List {
            Section("Driver") {
                row("Name", value: "Asurada Driver")
                row("Primary Car", value: "Porsche Cayman GT4")
                row("Units", value: "Metric")
            }
            .listRowBackground(SaabTheme.panel)

            Section("Library") {
                row("Vehicles", value: "3")
                row("Tracks", value: "6")
                row("Import Sources", value: "2")
            }
            .listRowBackground(SaabTheme.panel)

            Section("Preferences") {
                row("Default Compare Mode", value: "Selected vs Best Lap")
                row("Video Sync", value: "Enabled")
            }
            .listRowBackground(SaabTheme.panel)

            Section {
                Toggle(isOn: Binding(
                    get: { appState.testingModeEnabled },
                    set: { appState.setTestingMode($0) }
                )) {
                    Label("Enable Real USB Feed", systemImage: "waveform.path.ecg")
                        .foregroundStyle(SaabTheme.white)
                }
                .tint(SaabTheme.blue)

                if appState.testingModeEnabled {
                    sliderRow(
                        title: "Feed Rate",
                        valueText: "\(Int(appState.testingFeedHz.rounded())) Hz",
                        value: $appState.testingFeedHz,
                        range: 8...45
                    )

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Bridge File")
                            .font(.caption)
                            .foregroundStyle(SaabTheme.dim)
                        Text(appState.usbBridgePath)
                            .font(.caption.monospaced())
                            .foregroundStyle(SaabTheme.blue)
                            .textSelection(.enabled)
                    }

                    row("Bridge Status", value: appState.testingStatusText)
                    row("Packets", value: "\(appState.usbPacketsReceived)")

                    Button("Clear USB Bridge Log") {
                        appState.clearUSBBridgeLog()
                    }
                    .foregroundStyle(SaabTheme.red)

                    Button("Reset Live Stream") {
                        appState.resetLiveStream()
                    }
                    .foregroundStyle(SaabTheme.blue)
                }
            } header: {
                Text("Real Data Feed")
                    .foregroundStyle(SaabTheme.dim)
            } footer: {
                if appState.testingModeEnabled {
                    Text("USB bridge mode: external relay writes NDJSON packets into the bridge file path shown above.")
                } else {
                    Text("Turn on to read real telemetry from the USB bridge file.")
                }
            }
            .listRowBackground(SaabTheme.panel)
        }
        .scrollContentBackground(.hidden)
        .saabScreen()
        .navigationTitle("Profile")
    }

    private func row(_ title: String, value: String) -> some View {
        HStack {
            Text(title)
                .foregroundStyle(SaabTheme.white)
            Spacer()
            Text(value)
                .font(.system(.body, design: .monospaced).monospacedDigit())
                .foregroundStyle(SaabTheme.blue)
                .shadow(color: SaabTheme.blue.opacity(0.35), radius: 4)
        }
    }

    private func sliderRow(
        title: String,
        valueText: String,
        value: Binding<Double>,
        range: ClosedRange<Double>
    ) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(title)
                    .foregroundStyle(SaabTheme.white)
                Spacer()
                Text(valueText)
                    .font(.system(.body, design: .monospaced).monospacedDigit())
                    .foregroundStyle(SaabTheme.blue)
            }
            Slider(value: value, in: range)
                .tint(SaabTheme.blue)
        }
    }
}

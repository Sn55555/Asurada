import SwiftUI

struct SessionDetailView: View {
    @EnvironmentObject private var appState: AppState

    private var liveLaps: [LiveLapRecord] {
        appState.liveLapsForDisplay
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text(appState.liveTrackDisplayName)
                        .font(.largeTitle.bold())
                        .saabGlow(SaabTheme.white, radius: 5)
                    Text(headerSecondaryLine)
                        .foregroundStyle(SaabTheme.dim)
                    Text(headerTertiaryLine)
                        .font(.subheadline)
                        .foregroundStyle(SaabTheme.blue)
                }

                HStack(spacing: 12) {
                    StatChip(title: "Fastest", value: appState.liveBestLapText, tint: SaabTheme.blue)
                    StatChip(title: "Laps", value: "\(appState.liveCompletedLapCount)", tint: SaabTheme.white)
                    StatChip(title: "Consistency", value: "\(appState.liveConsistencyScore)", tint: SaabTheme.red)
                }

                VStack(alignment: .leading, spacing: 12) {
                    Text("Laps")
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)

                    if liveLaps.isEmpty {
                        Text("Waiting for real lap packets.")
                            .foregroundStyle(SaabTheme.dim)
                            .padding(.vertical, 4)
                    } else {
                        ForEach(liveLaps) { lap in
                            HStack {
                                Text("Lap \(lap.lapNumber)")
                                    .font(.headline)
                                    .foregroundStyle(lap.isComplete ? SaabTheme.white : SaabTheme.blue)
                                Spacer()
                                Text(appState.formatLapTime(seconds: lap.lapTimeSec))
                                    .font(.system(.subheadline, design: .monospaced).monospacedDigit())
                                    .saabGlow(lap.isComplete ? SaabTheme.white : SaabTheme.blue, radius: 4)
                                if !lap.isComplete {
                                    Text("Live")
                                        .font(.caption)
                                        .foregroundStyle(SaabTheme.blue)
                                }
                            }
                            if lap.id != liveLaps.last?.id {
                                Divider().overlay(SaabTheme.line)
                            }
                        }
                    }
                }
                .padding()
                .saabPanel(cornerRadius: 8, glow: SaabTheme.white)

                VStack(alignment: .leading, spacing: 12) {
                    Text("Events")
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(appState.liveRecentInsights.enumerated()), id: \.offset) { _, text in
                            Text(text)
                                .font(.subheadline)
                                .foregroundStyle(SaabTheme.white)
                        }
                    }
                    .padding()
                    .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
                }

                HStack(spacing: 12) {
                    Button {
                        appState.openReplay()
                    } label: {
                        footerAction("Replay Selected Lap", systemImage: "play.fill", tint: .blue)
                    }

                    Button {
                        appState.openCompare()
                    } label: {
                        footerAction("Compare With Best", systemImage: "arrow.left.arrow.right", tint: SaabTheme.blue)
                    }
                }
            }
            .padding()
        }
        .saabScreen()
        .navigationTitle("Session")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            appState.pollUSBBridgeNow()
        }
    }

    private var headerSecondaryLine: String {
        let trackLength = appState.liveTrackLengthMeters.map { "\($0)m" } ?? "length --"
        return "USB Live Stream • \(trackLength)"
    }

    private var headerTertiaryLine: String {
        "\(appState.liveLapDisplayText) • Updated \(appState.liveLastUpdateText)"
    }

    private func footerAction(_ title: String, systemImage: String, tint: Color) -> some View {
        Label(title, systemImage: systemImage)
            .font(.headline)
            .foregroundStyle(SaabTheme.white)
            .frame(maxWidth: .infinity)
            .padding()
            .saabPanel(cornerRadius: 8, glow: tint)
    }
}

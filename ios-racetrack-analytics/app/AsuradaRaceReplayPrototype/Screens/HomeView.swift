import SwiftUI

struct HomeView: View {
    @EnvironmentObject private var appState: AppState

    private var bestLapText: String {
        appState.liveBestLapText
    }

    private var consistencyText: String {
        "\(appState.liveConsistencyScore)"
    }

    private var summaryText: String {
        "Live USB stream at \(appState.liveTrackDisplayName)"
    }

    private var quickInsights: [String] {
        appState.liveRecentInsights
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Driver Summary")
                        .font(.title2.bold())
                        .saabGlow(SaabTheme.white, radius: 4)
                    Text(summaryText)
                        .foregroundStyle(SaabTheme.dim)
                }

                HStack(spacing: 12) {
                    StatChip(title: "Best Lap", value: bestLapText, tint: SaabTheme.blue)
                    StatChip(title: "Consistency", value: consistencyText, tint: SaabTheme.white)
                }

                RacingDigitalDash(compact: true)

                VStack(alignment: .leading, spacing: 12) {
                    Text("Quick Insights")
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)

                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(Array(quickInsights.enumerated()), id: \.offset) { _, text in
                            Text(text)
                                .foregroundStyle(SaabTheme.white)
                        }
                    }
                    .font(.subheadline)
                    .padding()
                    .saabPanel(cornerRadius: 8, glow: SaabTheme.white)
                }

                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text("Recent Session")
                            .font(.headline)
                            .foregroundStyle(SaabTheme.white)
                        Spacer()
                        NavigationLink("Open") {
                            SessionDetailView()
                        }
                        .foregroundStyle(SaabTheme.blue)
                    }

                    NavigationLink {
                        SessionDetailView()
                    } label: {
                        liveSessionCard
                    }
                    .buttonStyle(.plain)
                }

                HStack(spacing: 12) {
                    Button {
                        appState.openReplay()
                    } label: {
                        quickAction("Replay", systemImage: "play.fill")
                    }

                    Button {
                        appState.openCompare()
                    } label: {
                        quickAction("Compare", systemImage: "chart.line.uptrend.xyaxis")
                    }
                }
            }
            .padding()
        }
        .saabScreen()
        .navigationTitle("Home")
        .onAppear {
            appState.pollUSBBridgeNow()
        }
    }

    private var liveSessionCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(appState.liveTrackDisplayName)
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)
                    Text("USB Live Stream")
                        .font(.subheadline)
                        .foregroundStyle(SaabTheme.dim)
                }
                Spacer()
                Text(appState.liveBestLapText)
                    .font(.system(.title3, design: .monospaced).monospacedDigit().weight(.semibold))
                    .saabGlow(SaabTheme.blue)
            }

            HStack {
                Label(appState.liveLastUpdateText, systemImage: "calendar")
                Spacer()
                Label("\(appState.liveCompletedLapCount)", systemImage: "number.circle")
            }
            .font(.caption)
            .foregroundStyle(SaabTheme.dim)
        }
        .padding()
        .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
    }

    private func quickAction(_ title: String, systemImage: String) -> some View {
        Label(title, systemImage: systemImage)
            .font(.headline)
            .foregroundStyle(SaabTheme.white)
            .frame(maxWidth: .infinity)
            .padding()
            .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
    }
}

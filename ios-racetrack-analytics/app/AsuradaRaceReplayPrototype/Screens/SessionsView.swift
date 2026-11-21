import SwiftUI

struct SessionsView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        List {
            Section("Live USB Session") {
                NavigationLink {
                    SessionDetailView()
                } label: {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(appState.liveTrackDisplayName)
                            .font(.headline)
                            .foregroundStyle(SaabTheme.white)
                        Text("Best \(appState.liveBestLapText) • Laps \(appState.liveCompletedLapCount)")
                            .font(.system(.subheadline, design: .monospaced).monospacedDigit())
                            .foregroundStyle(SaabTheme.blue)
                            .shadow(color: SaabTheme.blue.opacity(0.55), radius: 4)
                        Text("Updated \(appState.liveLastUpdateText)")
                            .font(.caption)
                            .foregroundStyle(SaabTheme.dim)
                    }
                    .padding(.vertical, 6)
                }
                .listRowBackground(SaabTheme.panel)
            }

            Section("Real Laps") {
                if appState.liveLapsForDisplay.isEmpty {
                    Text("Waiting for real lap packets.")
                        .foregroundStyle(SaabTheme.dim)
                        .listRowBackground(SaabTheme.panel)
                } else {
                    ForEach(appState.liveLapsForDisplay) { lap in
                        HStack {
                            Text("Lap \(lap.lapNumber)")
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
                        .font(.subheadline)
                        .listRowBackground(SaabTheme.panel)
                    }
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .saabScreen()
        .navigationTitle("Sessions")
        .onAppear {
            appState.pollUSBBridgeNow()
        }
    }
}

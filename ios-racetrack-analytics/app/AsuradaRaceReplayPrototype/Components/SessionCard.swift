import SwiftUI

struct SessionCard: View {
    let session: SessionSummary

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(session.trackName)
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)
                    Text("\(session.carName) • \(session.sessionType)")
                        .font(.subheadline)
                        .foregroundStyle(SaabTheme.dim)
                }
                Spacer()
                Text(session.bestLap)
                    .font(.system(.title3, design: .monospaced).monospacedDigit().weight(.semibold))
                    .saabGlow(SaabTheme.blue)
            }

            HStack {
                Label(session.dateText, systemImage: "calendar")
                Spacer()
                Label("\(session.consistencyScore)", systemImage: "gauge.with.dots.needle.67percent")
            }
            .font(.caption)
            .foregroundStyle(SaabTheme.dim)
        }
        .padding()
        .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
    }
}

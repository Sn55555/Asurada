import SwiftUI

struct LapRow: View {
    let lap: LapSummary
    var isSelected = false

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Lap \(lap.lapNumber)")
                    .font(.headline)
                    .foregroundStyle(SaabTheme.white)
                Text(lap.deltaText)
                    .font(.caption)
                    .foregroundStyle(lap.deltaText == "Best" ? SaabTheme.blue : SaabTheme.dim)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 4) {
                Text(lap.lapTime)
                    .font(.system(.headline, design: .monospaced).monospacedDigit())
                    .saabGlow(lap.deltaText == "Best" ? SaabTheme.blue : SaabTheme.white, radius: 4)
                Text(lap.sectorTimes.joined(separator: "  "))
                    .font(.system(.caption, design: .monospaced).monospacedDigit())
                    .foregroundStyle(SaabTheme.dim)
            }

            Image(systemName: lap.isValid ? "checkmark.seal" : "xmark.octagon")
                .foregroundStyle(lap.isValid ? SaabTheme.blue : SaabTheme.red)
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 10)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(isSelected ? SaabTheme.blue.opacity(0.12) : .clear)
        )
    }
}

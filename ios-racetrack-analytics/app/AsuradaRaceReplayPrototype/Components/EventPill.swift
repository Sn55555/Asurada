import SwiftUI

struct EventPill: View {
    let event: EventMarker

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: event.symbol)
                .foregroundStyle(SaabTheme.blue)
            Text(event.title)
                .foregroundStyle(SaabTheme.white)
            Text(event.timeText)
                .foregroundStyle(SaabTheme.dim)
        }
        .font(.caption.weight(.medium))
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(SaabTheme.panelHot, in: Capsule())
        .overlay(Capsule().strokeBorder(SaabTheme.line, lineWidth: 1))
        .shadow(color: SaabTheme.blue.opacity(0.22), radius: 8)
    }
}

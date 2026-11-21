import SwiftUI

enum SaabTheme {
    static let black = Color.black
    static let panel = Color(red: 0.012, green: 0.014, blue: 0.018)
    static let panelHot = Color(red: 0.025, green: 0.03, blue: 0.04)
    static let line = Color.white.opacity(0.18)
    static let dim = Color.white.opacity(0.58)
    static let white = Color.white
    static let red = Color(red: 1.0, green: 0.12, blue: 0.08)
    static let blue = Color(red: 0.18, green: 0.52, blue: 1.0)

}

struct SaabPanelModifier: ViewModifier {
    var cornerRadius: CGFloat = 8
    var glow: Color = SaabTheme.blue

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(
                        LinearGradient(
                            colors: [SaabTheme.panelHot, SaabTheme.panel],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .strokeBorder(SaabTheme.line, lineWidth: 1)
            )
            .shadow(color: glow.opacity(0.24), radius: 12, x: 0, y: 0)
    }
}

struct SaabGlowModifier: ViewModifier {
    var color: Color = SaabTheme.white
    var radius: CGFloat = 6

    func body(content: Content) -> some View {
        content
            .foregroundStyle(color)
            .shadow(color: color.opacity(0.72), radius: radius, x: 0, y: 0)
            .shadow(color: color.opacity(0.30), radius: radius * 2, x: 0, y: 0)
    }
}

extension View {
    func saabPanel(cornerRadius: CGFloat = 8, glow: Color = SaabTheme.blue) -> some View {
        modifier(SaabPanelModifier(cornerRadius: cornerRadius, glow: glow))
    }

    func saabGlow(_ color: Color = SaabTheme.white, radius: CGFloat = 6) -> some View {
        modifier(SaabGlowModifier(color: color, radius: radius))
    }

    func saabScreen() -> some View {
        background(SaabTheme.black.ignoresSafeArea())
            .foregroundStyle(SaabTheme.white)
            .tint(SaabTheme.blue)
    }
}

struct StatChip: View {
    let title: String
    let value: String
    var tint: Color = .blue

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption2.weight(.semibold))
                .textCase(.uppercase)
                .foregroundStyle(SaabTheme.dim)
            Text(value)
                .font(.system(.headline, design: .monospaced).monospacedDigit().weight(.semibold))
                .saabGlow(tint, radius: 5)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .saabPanel(cornerRadius: 8, glow: tint)
    }
}

struct RacingDigitalDash: View {
    @EnvironmentObject private var appState: AppState
    var compact = false

    private var telemetry: TelemetryPoint {
        appState.replayCurrentTelemetry()
    }

    private var rpmProgress: Double {
        if telemetry.revLightsPercent > 0 {
            return Double(telemetry.revLightsPercent) / 100.0
        }
        return min(max(Double(telemetry.rpm) / 12_500.0, 0), 1)
    }

    var body: some View {
        VStack(spacing: compact ? 8 : 10) {
            shiftLightRow
            rpmSweep

            HStack(alignment: .center, spacing: compact ? 10 : 14) {
                sideColumn(alignment: .leading, items: leftItems)

                VStack(spacing: 4) {
                    Text(gearText)
                        .font(.system(size: compact ? 78 : 102, weight: .black, design: .rounded))
                        .minimumScaleFactor(0.6)
                        .lineLimit(1)
                        .saabGlow(gearColor, radius: 12)
                        .frame(width: compact ? 118 : 146, height: compact ? 82 : 104)
                    Text("GEAR")
                        .font(.caption.weight(.bold))
                        .foregroundStyle(SaabTheme.dim)
                }

                sideColumn(alignment: .trailing, items: rightItems)
            }

            HStack(spacing: 8) {
                bottomCell("LAP", value: lapText, color: SaabTheme.blue)
                bottomCell("TIME", value: appState.formatReplayTime(), color: SaabTheme.white)
                bottomCell("DRS", value: telemetry.drs ? "OPEN" : "OFF", color: telemetry.drs ? SaabTheme.blue : SaabTheme.dim)
            }
        }
        .padding(.horizontal, compact ? 14 : 18)
        .padding(.vertical, compact ? 12 : 16)
        .background(
            DashBezelShape(cornerCut: 22)
                .fill(
                    LinearGradient(
                        colors: [Color(red: 0.02, green: 0.025, blue: 0.034), Color.black],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
        )
        .overlay(DashBezelShape(cornerCut: 22).stroke(SaabTheme.line, lineWidth: 1.2))
        .overlay(alignment: .top) {
            Rectangle()
                .fill(SaabTheme.blue.opacity(0.42))
                .frame(height: 1)
                .padding(.horizontal, 42)
                .shadow(color: SaabTheme.blue.opacity(0.9), radius: 9)
        }
        .shadow(color: SaabTheme.blue.opacity(0.28), radius: 18)
    }

    private var shiftLightRow: some View {
        HStack(spacing: 5) {
            ForEach(0..<12, id: \.self) { index in
                Capsule()
                    .fill(index < activeShiftLights ? shiftLightColor(index) : SaabTheme.white.opacity(0.13))
                    .frame(width: compact ? 16 : 20, height: compact ? 6 : 7)
                    .shadow(color: index < activeShiftLights ? shiftLightColor(index).opacity(0.9) : .clear, radius: 7)
            }
        }
    }

    private var rpmSweep: some View {
        GeometryReader { proxy in
            let width = proxy.size.width
            let activeWidth = max(0, width * rpmProgress)
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(SaabTheme.white.opacity(0.10))
                    .frame(height: compact ? 16 : 20)

                Capsule()
                    .fill(
                        LinearGradient(
                            colors: [SaabTheme.blue, SaabTheme.white, SaabTheme.red],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .frame(width: activeWidth, height: compact ? 16 : 20)
                    .shadow(color: rpmProgress > 0.82 ? SaabTheme.red.opacity(0.75) : SaabTheme.blue.opacity(0.65), radius: 8)

                HStack {
                    ForEach(0..<8, id: \.self) { _ in
                        Rectangle()
                            .fill(Color.black.opacity(0.65))
                            .frame(width: 1)
                        Spacer()
                    }
                }
                .padding(.horizontal, 10)
            }
        }
        .frame(height: compact ? 18 : 22)
    }

    private var activeShiftLights: Int {
        min(12, max(0, Int((rpmProgress * 12.0).rounded(.up))))
    }

    private func shiftLightColor(_ index: Int) -> Color {
        if index >= 10 { return SaabTheme.red }
        if index >= 7 { return SaabTheme.white }
        return SaabTheme.blue
    }

    private var leftItems: [DashReadout] {
        [
            DashReadout(label: "SPD", value: "\(Int(telemetry.speed.rounded()))", unit: "km/h", color: SaabTheme.blue),
            DashReadout(label: "RPM", value: telemetry.rpm > 0 ? "\(telemetry.rpm)" : "--", unit: "", color: rpmProgress > 0.84 ? SaabTheme.red : SaabTheme.white),
            DashReadout(label: "THR", value: "\(Int((telemetry.throttle * 100).rounded()))", unit: "%", color: SaabTheme.white)
        ]
    }

    private var rightItems: [DashReadout] {
        [
            DashReadout(label: "POS", value: positionText, unit: "", color: SaabTheme.white),
            DashReadout(label: "BRK", value: "\(Int((telemetry.brake * 100).rounded()))", unit: "%", color: telemetry.brake > 0.35 ? SaabTheme.red : SaabTheme.white),
            DashReadout(label: "STR", value: steerText, unit: "", color: abs(telemetry.steer) > 0.65 ? SaabTheme.red : SaabTheme.blue)
        ]
    }

    private func sideColumn(alignment: HorizontalAlignment, items: [DashReadout]) -> some View {
        VStack(alignment: alignment, spacing: compact ? 6 : 8) {
            ForEach(items) { item in
                VStack(alignment: alignment, spacing: 2) {
                    Text(item.label)
                        .font(.caption2.weight(.black))
                        .foregroundStyle(SaabTheme.dim)
                    HStack(alignment: .firstTextBaseline, spacing: 3) {
                        Text(item.value)
                            .font(.system(compact ? .title3 : .title2, design: .monospaced).monospacedDigit().weight(.black))
                            .minimumScaleFactor(0.58)
                            .lineLimit(1)
                            .saabGlow(item.color, radius: 6)
                        if !item.unit.isEmpty {
                            Text(item.unit)
                                .font(.caption2.weight(.bold))
                                .foregroundStyle(SaabTheme.dim)
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: alignment == .leading ? .leading : .trailing)
            }
        }
        .frame(maxWidth: .infinity)
    }

    private func bottomCell(_ label: String, value: String, color: Color) -> some View {
        VStack(spacing: 2) {
            Text(label)
                .font(.caption2.weight(.black))
                .foregroundStyle(SaabTheme.dim)
            Text(value)
                .font(.system(.caption, design: .monospaced).monospacedDigit().weight(.bold))
                .lineLimit(1)
                .minimumScaleFactor(0.72)
                .saabGlow(color, radius: 4)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .background(SaabTheme.black.opacity(0.58), in: RoundedRectangle(cornerRadius: 6, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).strokeBorder(SaabTheme.line, lineWidth: 1))
    }

    private var gearText: String {
        switch telemetry.gear {
        case -1: return "R"
        case 0: return "N"
        default: return "\(telemetry.gear)"
        }
    }

    private var gearColor: Color {
        telemetry.gear <= 0 ? SaabTheme.dim : SaabTheme.white
    }

    private var lapText: String {
        guard appState.liveLapNumber > 0 else { return "--" }
        if let total = appState.liveTotalLaps, total > 0 {
            return "\(appState.liveLapNumber)/\(total)"
        }
        return "\(appState.liveLapNumber)"
    }

    private var positionText: String {
        guard let position = appState.liveCarPosition else { return "--" }
        return "P\(position)"
    }

    private var steerText: String {
        String(format: "%+d", Int((telemetry.steer * 100).rounded()))
    }
}

private struct DashReadout: Identifiable {
    let id = UUID()
    let label: String
    let value: String
    let unit: String
    let color: Color
}

private struct DashBezelShape: Shape {
    var cornerCut: CGFloat

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + cornerCut, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - cornerCut, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.minY + cornerCut))
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - cornerCut * 0.72))
        path.addLine(to: CGPoint(x: rect.maxX - cornerCut * 0.72, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX + cornerCut * 0.72, y: rect.maxY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.maxY - cornerCut * 0.72))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + cornerCut))
        path.closeSubpath()
        return path
    }
}

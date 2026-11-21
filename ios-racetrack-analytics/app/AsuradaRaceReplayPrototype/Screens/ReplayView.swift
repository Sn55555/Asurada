import Charts
import Combine
import SwiftUI

struct ReplayView: View {
    @EnvironmentObject private var appState: AppState

    @State private var selectedMetric: ReplayMetric = .speed
    @State private var wasPlayingBeforeScrub = false

    private let playbackTimer = Timer.publish(every: 0.05, on: .main, in: .common).autoconnect()

    private var telemetrySeries: [TelemetryPoint] {
        appState.replayChartSeries()
    }

    private var chartRows: [ReplayChartPoint] {
        switch selectedMetric {
        case .speed:
            return telemetrySeries.map { ReplayChartPoint(second: $0.second, value: $0.speed, signal: "Speed") }
        case .throttleBrake:
            return telemetrySeries.flatMap { point in
                [
                    ReplayChartPoint(second: point.second, value: point.throttle * 100, signal: "Throttle"),
                    ReplayChartPoint(second: point.second, value: point.brake * 100, signal: "Brake")
                ]
            }
        case .delta:
            return telemetrySeries.map { ReplayChartPoint(second: $0.second, value: $0.delta, signal: "Delta") }
        }
    }

    private var currentTelemetry: TelemetryPoint {
        appState.replayCurrentTelemetry()
    }

    private var chartCursorSecond: Double {
        if appState.testingModeEnabled {
            return telemetrySeries.last?.second ?? 0
        }
        let domainEnd = telemetrySeries.last?.second ?? 1
        return appState.replayProgress * domainEnd
    }

    private var isUsingLiveWorldTrack: Bool {
        appState.liveWorldPath.count > 2
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                trackStage

                if appState.testingModeEnabled {
                    testingStatusBar
                }

                RacingDigitalDash()

                HStack(spacing: 10) {
                    StatChip(title: "Speed", value: "\(Int(currentTelemetry.speed.rounded())) km/h", tint: SaabTheme.blue)
                    StatChip(title: "Throttle", value: "\(Int((currentTelemetry.throttle * 100).rounded()))%", tint: SaabTheme.white)
                    StatChip(title: "Brake", value: "\(Int((currentTelemetry.brake * 100).rounded()))%", tint: SaabTheme.red)
                    StatChip(title: "Gear", value: gearText, tint: SaabTheme.white)
                }

                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Button {
                            appState.skipReplay(by: -0.1)
                        } label: {
                            Image(systemName: "backward.end.fill")
                                .foregroundStyle(SaabTheme.blue)
                        }

                        Button {
                            appState.toggleReplay()
                        } label: {
                            Image(systemName: appState.isReplayPlaying ? "pause.fill" : "play.fill")
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(SaabTheme.blue)

                        Button {
                            appState.skipReplay(by: 0.1)
                        } label: {
                            Image(systemName: "forward.end.fill")
                                .foregroundStyle(SaabTheme.blue)
                        }

                        Spacer()

                        Text(appState.formatReplayTime())
                            .font(.system(.headline, design: .monospaced).monospacedDigit())
                            .saabGlow(SaabTheme.white, radius: 5)
                    }

                    Slider(
                        value: Binding(
                            get: { appState.replayProgress },
                            set: { appState.setReplayProgress($0) }
                        ),
                        in: 0...1,
                        onEditingChanged: sliderEditingChanged
                    )
                }

                Picker("Metric", selection: $selectedMetric) {
                    ForEach(ReplayMetric.allCases, id: \.self) { metric in
                        Text(metric.title).tag(metric)
                    }
                }
                .pickerStyle(.segmented)
                .tint(SaabTheme.blue)

                chartCard

                VStack(alignment: .leading, spacing: 12) {
                    Text("Live Notes")
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)

                    ForEach(Array(appState.liveRecentInsights.enumerated()), id: \.offset) { _, text in
                        Text(text)
                            .font(.subheadline)
                            .foregroundStyle(SaabTheme.white)
                    }
                }
                .padding()
                .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
            }
            .padding()
        }
        .saabScreen()
        .navigationTitle("Replay")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            if appState.testingModeEnabled && appState.liveTelemetrySeries.isEmpty {
                appState.resetLiveStream()
            }
            appState.pollUSBBridgeNow()
        }
        .onReceive(playbackTimer) { _ in
            appState.tickReplay(delta: 0.05)
        }
    }

    private var trackStage: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(appState.liveTrackDisplayName)
                        .font(.headline)
                        .saabGlow(SaabTheme.white, radius: 4)
                    Text(trackSubtitleText)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(SaabTheme.dim)
                }
                Spacer()
                Image(systemName: "video")
                    .foregroundStyle(SaabTheme.blue)
                    .shadow(color: SaabTheme.blue.opacity(0.7), radius: 6)
            }

            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(SaabTheme.panel)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .strokeBorder(SaabTheme.line, lineWidth: 1)
                    )
                    .shadow(color: SaabTheme.blue.opacity(0.24), radius: 18)
                    .frame(height: 280)

                if isUsingLiveWorldTrack {
                    WorldTrackShape(points: appState.liveWorldPath, trim: 1.0)
                        .stroke(style: StrokeStyle(lineWidth: 16, lineCap: .round, lineJoin: .round))
                        .foregroundStyle(SaabTheme.white.opacity(0.10))
                        .padding(40)
                        .frame(height: 260)

                    WorldTrackShape(points: appState.liveWorldPath, trim: 1.0)
                        .stroke(style: StrokeStyle(lineWidth: 16, lineCap: .round, lineJoin: .round))
                        .foregroundStyle(SaabTheme.blue)
                        .shadow(color: SaabTheme.blue.opacity(0.7), radius: 12)
                        .padding(40)
                        .frame(height: 260)
                } else {
                    TrackMapShape()
                        .stroke(style: StrokeStyle(lineWidth: 16, lineCap: .round, lineJoin: .round))
                        .foregroundStyle(SaabTheme.white.opacity(0.10))
                        .padding(40)
                        .frame(height: 260)

                    TrackMapShape(trim: appState.replayProgress)
                        .stroke(style: StrokeStyle(lineWidth: 16, lineCap: .round, lineJoin: .round))
                        .foregroundStyle(SaabTheme.blue)
                        .shadow(color: SaabTheme.blue.opacity(0.7), radius: 12)
                        .padding(40)
                        .frame(height: 260)
                }

                movingMarker
            }
        }
    }

    private var movingMarker: some View {
        GeometryReader { proxy in
            Circle()
                .fill(SaabTheme.red)
                .frame(width: 18, height: 18)
                .overlay(Circle().stroke(SaabTheme.white, lineWidth: 2))
                .shadow(color: SaabTheme.red.opacity(0.9), radius: 12)
                .position(markerPosition(in: proxy.size))
        }
    }

    private func markerPosition(in size: CGSize) -> CGPoint {
        if isUsingLiveWorldTrack,
           let point = WorldTrackProjector.lastProjectedPoint(for: appState.liveWorldPath, in: CGRect(origin: .zero, size: size), padding: 40) {
            return point
        }
        return CGPoint(x: size.width * markerX, y: size.height * markerY)
    }

    private var markerX: CGFloat {
        0.18 + CGFloat(appState.replayProgress) * 0.62
    }

    private var markerY: CGFloat {
        0.24 + CGFloat(sin(appState.replayProgress * .pi * 2 + 0.6) * 0.18 + 0.34)
    }

    private var trackSubtitleText: String {
        "\(appState.liveLapDisplayText) • \(appState.testingFeedSource.rawValue)"
    }

    private var chartCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(selectedMetric.title)
                .font(.headline)
                .foregroundStyle(SaabTheme.white)

            Chart(chartRows) { point in
                LineMark(x: .value("Second", point.second), y: .value(point.signal, point.value))
                    .foregroundStyle(by: .value("Signal", point.signal))
            }
            .chartForegroundStyleScale([
                "Speed": SaabTheme.blue,
                "Throttle": SaabTheme.white,
                "Brake": SaabTheme.red,
                "Delta": SaabTheme.blue
            ])
            .chartXAxis {
                AxisMarks { _ in
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(SaabTheme.line)
                    AxisValueLabel().foregroundStyle(SaabTheme.dim)
                }
            }
            .chartYAxis {
                AxisMarks { _ in
                    AxisGridLine(stroke: StrokeStyle(lineWidth: 0.5)).foregroundStyle(SaabTheme.line)
                    AxisValueLabel().foregroundStyle(SaabTheme.dim)
                }
            }
            .chartLegend(position: .bottom, alignment: .leading)
            .chartOverlay { proxy in
                GeometryReader { geo in
                    if let x = proxy.position(forX: chartCursorSecond) {
                        Rectangle()
                            .fill(SaabTheme.red.opacity(0.70))
                            .frame(width: 2, height: geo.size.height)
                            .position(x: x, y: geo.size.height / 2)
                    }
                }
            }
            .frame(height: 220)
        }
        .padding()
        .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
    }

    private var gearText: String {
        switch currentTelemetry.gear {
        case -1: return "R"
        case 0: return "N"
        default: return "\(currentTelemetry.gear)"
        }
    }

    private var rpmText: String {
        currentTelemetry.rpm > 0 ? "\(currentTelemetry.rpm)" : "--"
    }

    private var testingStatusBar: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label("Live Data Feed Active", systemImage: "dot.radiowaves.left.and.right")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(SaabTheme.white)
                Spacer()
                Text(appState.testingFeedSource.rawValue)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(SaabTheme.blue)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(SaabTheme.blue.opacity(0.14), in: Capsule())
            }
            Text(appState.testingStatusText)
                .font(.caption)
                .foregroundStyle(SaabTheme.dim)
            HStack(spacing: 14) {
                metricBadge("Hz", value: String(format: "%.0f", appState.testingFeedHz))
                metricBadge("Packets", value: "\(appState.usbPacketsReceived)")
            }
        }
        .padding(12)
        .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
    }

    private func metricBadge(_ title: String, value: String) -> some View {
        HStack(spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundStyle(SaabTheme.dim)
            Text(value)
                .font(.system(.caption, design: .monospaced).monospacedDigit().weight(.semibold))
                .saabGlow(SaabTheme.white, radius: 3)
        }
    }

    private func sliderEditingChanged(_ editing: Bool) {
        if editing {
            wasPlayingBeforeScrub = appState.isReplayPlaying
            appState.isReplayPlaying = false
        } else if wasPlayingBeforeScrub {
            appState.isReplayPlaying = true
            wasPlayingBeforeScrub = false
        }
    }

}

private enum ReplayMetric: CaseIterable {
    case speed
    case throttleBrake
    case delta

    var title: String {
        switch self {
        case .speed: return "Speed"
        case .throttleBrake: return "Throttle / Brake"
        case .delta: return "Delta"
        }
    }
}

private struct ReplayChartPoint: Identifiable {
    let second: Double
    let value: Double
    let signal: String

    var id: String { "\(signal)-\(second)" }
}

private struct TrackMapShape: Shape {
    var trim: Double = 1.0

    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + rect.width * 0.18, y: rect.minY + rect.height * 0.20))
        path.addCurve(
            to: CGPoint(x: rect.minX + rect.width * 0.74, y: rect.minY + rect.height * 0.18),
            control1: CGPoint(x: rect.minX + rect.width * 0.34, y: rect.minY + rect.height * 0.02),
            control2: CGPoint(x: rect.minX + rect.width * 0.64, y: rect.minY + rect.height * 0.04)
        )
        path.addCurve(
            to: CGPoint(x: rect.minX + rect.width * 0.82, y: rect.minY + rect.height * 0.58),
            control1: CGPoint(x: rect.minX + rect.width * 0.86, y: rect.minY + rect.height * 0.26),
            control2: CGPoint(x: rect.minX + rect.width * 0.90, y: rect.minY + rect.height * 0.42)
        )
        path.addCurve(
            to: CGPoint(x: rect.minX + rect.width * 0.28, y: rect.minY + rect.height * 0.76),
            control1: CGPoint(x: rect.minX + rect.width * 0.72, y: rect.minY + rect.height * 0.82),
            control2: CGPoint(x: rect.minX + rect.width * 0.42, y: rect.minY + rect.height * 0.92)
        )
        path.addCurve(
            to: CGPoint(x: rect.minX + rect.width * 0.18, y: rect.minY + rect.height * 0.20),
            control1: CGPoint(x: rect.minX + rect.width * 0.16, y: rect.minY + rect.height * 0.62),
            control2: CGPoint(x: rect.minX + rect.width * 0.10, y: rect.minY + rect.height * 0.38)
        )
        return path.trimmedPath(from: 0, to: trim)
    }
}

private struct WorldTrackShape: Shape {
    let points: [WorldPoint]
    var trim: Double = 1.0

    func path(in rect: CGRect) -> Path {
        let projected = WorldTrackProjector.projectedPoints(for: points, in: rect, padding: 0)
        guard projected.count > 1 else { return Path() }

        var path = Path()
        path.move(to: projected[0])
        for point in projected.dropFirst() {
            path.addLine(to: point)
        }
        return path.trimmedPath(from: 0, to: trim)
    }
}

private enum WorldTrackProjector {
    static func projectedPoints(for points: [WorldPoint], in rect: CGRect, padding: CGFloat) -> [CGPoint] {
        guard points.count > 1 else { return [] }

        var minX = points[0].x
        var maxX = points[0].x
        var minY = points[0].y
        var maxY = points[0].y

        for point in points.dropFirst() {
            minX = min(minX, point.x)
            maxX = max(maxX, point.x)
            minY = min(minY, point.y)
            maxY = max(maxY, point.y)
        }

        let dataWidth = max(1.0, maxX - minX)
        let dataHeight = max(1.0, maxY - minY)
        let drawWidth = max(1.0, rect.width - padding * 2)
        let drawHeight = max(1.0, rect.height - padding * 2)
        let scale = min(drawWidth / dataWidth, drawHeight / dataHeight)

        let offsetX = rect.minX + (rect.width - dataWidth * scale) / 2
        let offsetY = rect.minY + (rect.height - dataHeight * scale) / 2

        return points.map { point in
            let x = offsetX + (point.x - minX) * scale
            // Flip Y so map orientation matches top-down expectation.
            let y = offsetY + (maxY - point.y) * scale
            return CGPoint(x: x, y: y)
        }
    }

    static func lastProjectedPoint(for points: [WorldPoint], in rect: CGRect, padding: CGFloat) -> CGPoint? {
        projectedPoints(for: points, in: rect, padding: padding).last
    }
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}

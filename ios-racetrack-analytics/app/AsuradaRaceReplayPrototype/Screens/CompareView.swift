import Charts
import SwiftUI

struct CompareView: View {
    @EnvironmentObject private var appState: AppState
    @State private var selectedMetric: CompareMetric = .delta
    @State private var liveLapAID: UUID?
    @State private var liveLapBID: UUID?

    private var liveLaps: [LiveLapRecord] {
        appState.liveCompareCandidates
    }

    private var liveLapA: LiveLapRecord? {
        guard let liveLapAID else { return nil }
        return liveLaps.first(where: { $0.id == liveLapAID })
    }

    private var liveLapB: LiveLapRecord? {
        guard let liveLapBID else { return nil }
        return liveLaps.first(where: { $0.id == liveLapBID })
    }

    private var comparisonSeries: [ComparisonPoint] {
        guard let liveLapA, let liveLapB else { return [] }
        let a = liveLapA.telemetry
        let b = liveLapB.telemetry

        let count = min(a.count, b.count)
        guard count > 0 else { return [] }

        return (0..<count).map { index in
            ComparisonPoint(
                second: min(a[index].second, b[index].second),
                secondA: a[index].second,
                secondB: b[index].second,
                speedA: a[index].speed,
                speedB: b[index].speed,
                throttleA: a[index].throttle,
                throttleB: b[index].throttle,
                brakeA: a[index].brake,
                brakeB: b[index].brake,
                deltaA: a[index].delta,
                deltaB: b[index].delta
            )
        }
    }

    private var totalDelta: Double {
        guard let liveLapA, let liveLapB else { return 0 }
        return liveLapA.lapTimeSec - liveLapB.lapTimeSec
    }

    private var chartRows: [CompareChartPoint] {
        switch selectedMetric {
        case .delta:
            return comparisonSeries.map {
                CompareChartPoint(second: $0.second, value: $0.timeDelta, signal: "Delta")
            }
        case .speed:
            return comparisonSeries.flatMap {
                [
                    CompareChartPoint(second: $0.second, value: $0.speedA, signal: "Speed A"),
                    CompareChartPoint(second: $0.second, value: $0.speedB, signal: "Speed B")
                ]
            }
        case .throttleBrake:
            return comparisonSeries.flatMap {
                [
                    CompareChartPoint(second: $0.second, value: $0.throttleA * 100, signal: "Throttle A"),
                    CompareChartPoint(second: $0.second, value: $0.throttleB * 100, signal: "Throttle B"),
                    CompareChartPoint(second: $0.second, value: $0.brakeA * 100, signal: "Brake A"),
                    CompareChartPoint(second: $0.second, value: $0.brakeB * 100, signal: "Brake B")
                ]
            }
        }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Lap Selection")
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)

                    if liveLaps.count < 2 {
                        Text("Waiting for at least 2 real laps from USB stream to compare.")
                            .foregroundStyle(SaabTheme.dim)
                    } else {
                        HStack(spacing: 12) {
                            liveLapPickerCard(
                                title: "Lap A",
                                selection: Binding(
                                    get: { liveLapAID ?? liveLaps.first?.id ?? UUID() },
                                    set: { liveLapAID = $0 }
                                )
                            )

                            liveLapPickerCard(
                                title: "Lap B",
                                selection: Binding(
                                    get: { liveLapBID ?? liveLaps.last?.id ?? UUID() },
                                    set: { liveLapBID = $0 }
                                )
                            )
                        }
                    }
                }

                VStack(alignment: .leading, spacing: 10) {
                    Text("Delta Summary")
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)

                    VStack(alignment: .leading, spacing: 8) {
                        Text(String(format: "%+.3fs", totalDelta))
                            .font(.system(size: 40, weight: .bold, design: .monospaced))
                            .saabGlow(totalDelta <= 0 ? SaabTheme.blue : SaabTheme.red, radius: 9)
                        Text(summaryText)
                            .foregroundStyle(SaabTheme.dim)
                    }
                    .padding()
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .saabPanel(cornerRadius: 8, glow: totalDelta <= 0 ? SaabTheme.blue : SaabTheme.red)
                }

                VStack(alignment: .leading, spacing: 10) {
                    Text("Gain / Loss by Track")
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)

                    HStack(spacing: 0) {
                        ForEach(trackSegments, id: \.index) { segment in
                            Rectangle()
                                .fill(color(for: segment.delta))
                        }
                    }
                    .frame(height: 16)
                    .clipShape(Capsule())
                    .overlay(Capsule().strokeBorder(SaabTheme.line, lineWidth: 1))
                    .shadow(color: SaabTheme.blue.opacity(0.24), radius: 8)
                }

                Picker("Metric", selection: $selectedMetric) {
                    ForEach(CompareMetric.allCases, id: \.self) { metric in
                        Text(metric.title).tag(metric)
                    }
                }
                .pickerStyle(.segmented)
                .tint(SaabTheme.blue)

                chartCard

                VStack(alignment: .leading, spacing: 12) {
                    Text("Corner Analysis")
                        .font(.headline)
                        .foregroundStyle(SaabTheme.white)
                    ForEach(liveCornerInsights) { insight in
                        liveInsightCard(insight)
                    }
                }
            }
            .padding()
        }
        .saabScreen()
        .navigationTitle("Compare")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            appState.pollUSBBridgeNow()
            ensureLiveLapSelection()
        }
        .onChange(of: liveLaps.map(\.id)) {
            ensureLiveLapSelection()
        }
    }

    private var summaryText: String {
        if liveLaps.count < 2 {
            return "Collecting live laps for comparison."
        }
        if totalDelta <= 0 {
            return "Lap A is currently faster in this real-stream comparison."
        }
        return "Lap A is currently slower in this real-stream comparison."
    }

    private var trackSegments: [(index: Int, delta: Double)] {
        guard !comparisonSeries.isEmpty else { return [] }
        let sectionCount = 5
        let chunkSize = max(1, comparisonSeries.count / sectionCount)

        return (0..<sectionCount).map { sectionIndex in
            let start = sectionIndex * chunkSize
            let end = min(comparisonSeries.count, start + chunkSize)
            let slice = comparisonSeries[start..<end]
            let avg = slice.map(\.timeDelta).reduce(0, +) / Double(max(1, slice.count))
            return (sectionIndex, avg)
        }
    }

    private func color(for delta: Double) -> Color {
        if delta < -0.03 { return SaabTheme.blue.opacity(0.82) }
        if delta < 0.03 { return SaabTheme.white.opacity(0.56) }
        return SaabTheme.red.opacity(0.82)
    }

    private func ensureLiveLapSelection() {
        guard liveLaps.count >= 2 else {
            liveLapAID = nil
            liveLapBID = nil
            return
        }

        let sorted = liveLaps.sorted(by: { $0.lapNumber < $1.lapNumber })
        let fallbackA = sorted[max(0, sorted.count - 2)].id
        let fallbackB = sorted[sorted.count - 1].id

        if liveLapAID == nil || !liveLaps.contains(where: { $0.id == liveLapAID }) {
            liveLapAID = fallbackA
        }
        if liveLapBID == nil || !liveLaps.contains(where: { $0.id == liveLapBID }) {
            liveLapBID = fallbackB
        }
        if liveLapAID == liveLapBID {
            liveLapAID = fallbackA
            liveLapBID = fallbackB
        }
    }

    private func liveLapPickerCard(title: String, selection: Binding<UUID>) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.caption)
                .foregroundStyle(SaabTheme.dim)

            Picker(title, selection: selection) {
                ForEach(liveLaps) { lap in
                    Text(liveLapLabel(lap)).tag(lap.id)
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding()
        .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
    }

    private func liveLapLabel(_ lap: LiveLapRecord) -> String {
        let minutes = Int(lap.lapTimeSec) / 60
        let seconds = Int(lap.lapTimeSec) % 60
        let millis = Int((lap.lapTimeSec * 1000).rounded()) % 1000
        let time = String(format: "%d:%02d.%03d", minutes, seconds, millis)
        return "Lap \(lap.lapNumber) • \(time)\(lap.isComplete ? "" : " • Live")"
    }

    private var liveCornerInsights: [LiveCornerInsight] {
        guard !comparisonSeries.isEmpty else {
            return [
                LiveCornerInsight(
                    id: 0,
                    title: "Segment Data",
                    entry: "n/a",
                    mid: "n/a",
                    exit: "n/a",
                    note: "Waiting for enough real-stream data points."
                )
            ]
        }

        let sectionCount = 3
        let chunkSize = max(1, comparisonSeries.count / sectionCount)
        return (0..<sectionCount).map { index in
            let start = index * chunkSize
            let end = min(comparisonSeries.count, start + chunkSize)
            let slice = comparisonSeries[start..<end]

            let entry = average(slice.map { $0.speedA - $0.speedB })
            let mid = average(slice.map { ($0.throttleA - $0.throttleB) * 100 })
            let exit = average(slice.map { ($0.brakeA - $0.brakeB) * 100 })
            let delta = average(slice.map(\.timeDelta))

            let note: String
            if delta < -0.03 {
                note = "Lap A gains time in this segment."
            } else if delta > 0.03 {
                note = "Lap A loses time in this segment."
            } else {
                note = "Segment pace is closely matched."
            }

            return LiveCornerInsight(
                id: index,
                title: "Segment \(index + 1)",
                entry: String(format: "%+.1f km/h", entry),
                mid: String(format: "%+.1f%% throttle", mid),
                exit: String(format: "%+.1f%% brake", exit),
                note: note
            )
        }
    }

    private func liveInsightCard(_ insight: LiveCornerInsight) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(insight.title)
                    .font(.headline)
                    .foregroundStyle(SaabTheme.white)
                Spacer()
            }

            Text("Entry \(insight.entry) • Mid \(insight.mid) • Exit \(insight.exit)")
                .font(.system(.caption, design: .monospaced).monospacedDigit())
                .foregroundStyle(SaabTheme.blue)
                .shadow(color: SaabTheme.blue.opacity(0.45), radius: 4)

            Text(insight.note)
                .font(.subheadline)
                .foregroundStyle(SaabTheme.dim)
        }
        .padding()
        .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
    }

    private func average(_ values: [Double]) -> Double {
        guard !values.isEmpty else { return 0 }
        return values.reduce(0, +) / Double(values.count)
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
                "Delta": SaabTheme.blue,
                "Speed A": SaabTheme.blue,
                "Speed B": SaabTheme.white,
                "Throttle A": SaabTheme.white,
                "Throttle B": SaabTheme.blue,
                "Brake A": SaabTheme.red,
                "Brake B": SaabTheme.red.opacity(0.55)
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
            .frame(height: 240)
        }
        .padding()
        .saabPanel(cornerRadius: 8, glow: SaabTheme.blue)
    }
}

private enum CompareMetric: CaseIterable {
    case delta
    case speed
    case throttleBrake

    var title: String {
        switch self {
        case .delta: return "Delta"
        case .speed: return "Speed"
        case .throttleBrake: return "Throttle / Brake"
        }
    }
}

private struct ComparisonPoint: Identifiable {
    let second: Double
    let secondA: Double
    let secondB: Double
    let speedA: Double
    let speedB: Double
    let throttleA: Double
    let throttleB: Double
    let brakeA: Double
    let brakeB: Double
    let deltaA: Double
    let deltaB: Double

    var id: Double { second }
    var timeDelta: Double {
        let bySecond = secondA - secondB
        if abs(bySecond) > 0.0001 {
            return bySecond
        }
        return deltaB - deltaA
    }
}

private struct LiveCornerInsight: Identifiable {
    let id: Int
    let title: String
    let entry: String
    let mid: String
    let exit: String
    let note: String
}

private struct CompareChartPoint: Identifiable {
    let second: Double
    let value: Double
    let signal: String

    var id: String { "\(signal)-\(second)" }
}

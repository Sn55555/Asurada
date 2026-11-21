import ActivityKit
import Foundation
@preconcurrency import Network
import OSLog

private let liveActivityLogger = Logger(subsystem: "com.asurada.AsuradaRaceReplayPrototype", category: "DamageLiveActivity")

enum AppTab: Int, Hashable {
    case home
    case sessions
    case replay
    case compare
    case profile
}

enum TestingFeedSource: String, CaseIterable, Identifiable {
    case usbBridge = "USB Bridge"

    var id: String { rawValue }
}

@MainActor
final class AppState: ObservableObject {
    @Published var selectedTab: AppTab = .home

    @Published var replayProgress: Double = 0.0
    @Published var isReplayPlaying = false

    // Testing environment controls.
    @Published var testingModeEnabled = true
    @Published var testingFeedSource: TestingFeedSource = .usbBridge
    @Published var testingFeedHz: Double = 20
    @Published private(set) var liveTelemetrySample = TelemetryPoint(
        second: 0,
        speed: 0,
        throttle: 0,
        brake: 0,
        delta: 0,
        steer: 0,
        gear: 0,
        rpm: 0,
        drs: false,
        revLightsPercent: 0
    )
    @Published private(set) var liveTelemetrySeries: [TelemetryPoint] = []
    @Published private(set) var usbBridgePath: String = ""
    @Published private(set) var usbBridgeStatus: String = "Idle"
    @Published private(set) var usbPacketsReceived: Int = 0
    @Published private(set) var liveTrackName: String = ""
    @Published private(set) var liveTrackId: Int?
    @Published private(set) var liveTrackLengthMeters: Int?
    @Published private(set) var liveLapNumber: Int = 0
    @Published private(set) var liveCarPosition: Int?
    @Published private(set) var liveTotalLaps: Int?
    @Published private(set) var liveSector: Int?
    @Published private(set) var liveCurrentLapTimeSec: Double?
    @Published private(set) var liveLastLapTimeSec: Double?
    @Published private(set) var liveWorldPath: [WorldPoint] = []
    @Published private(set) var liveCompletedLaps: [LiveLapRecord] = []
    @Published private(set) var liveDamage: CarDamageState = .empty
    @Published private(set) var liveUpdatedAt: Date?
    @Published private(set) var foregroundDamageIslandState: RaceDamageActivityAttributes.ContentState?
    @Published private(set) var foregroundDamageIslandExpanded = false

    private let maxLiveSampleCount = 320
    private let maxLiveWorldPointCount = 1600
    private let networkTelemetryPort: UInt16 = 9077
    private let minLiveLapSampleCount = 60
    private let maxLiveLapSampleCount = 8_000
    private let minValidLapDurationSec = 40.0
    private let maxValidLapDurationSec = 400.0
    private let tyreWearCriticalPct = 70.0
    private let tyreDamageCriticalPct = 30.0
    private let structuralDamageCriticalPct = 30.0
    private let emptyTelemetrySample = TelemetryPoint(
        second: 0,
        speed: 0,
        throttle: 0,
        brake: 0,
        delta: 0,
        steer: 0,
        gear: 0,
        rpm: 0,
        drs: false,
        revLightsPercent: 0
    )
    private var liveClock: Double = 0
    private var packetAccumulator: Double = 0
    private var usbReadOffset: UInt64 = 0
    private var usbPendingFragment = ""
    private var buildingLapNumber: Int?
    private var buildingLapSamples: [TelemetryPoint] = []
    private var buildingLapMaxCurrentTimeSec: Double = 0
    private var liveActivityTask: Task<Void, Never>?
    private var liveActivityCollapseTask: Task<Void, Never>?
    private var lastLiveActivityState: RaceDamageActivityAttributes.ContentState?
    private var lastLiveActivityExpansionKey: String?
    private var liveActivityExpandedUntil: Date?
    private var foregroundDamageIslandToken = UUID()
    private var telemetryListener: NWListener?
    private var telemetryConnections: [NWConnection] = []
    private var telemetryPendingFragments: [ObjectIdentifier: String] = [:]

    init() {
        usbBridgePath = usbBridgeFileURL.path
        resetLiveStream()
        startWiFiTelemetryListener()
    }

    var replayDurationSeconds: Double {
        let candidate = liveCurrentLapTimeSec
            ?? liveLastLapTimeSec
            ?? activeLiveLapRecord()?.lapTimeSec
            ?? liveBestLapSec
            ?? liveTelemetrySeries.last?.second
            ?? 1.0
        return max(1.0, candidate)
    }

    var replayElapsedSeconds: Double {
        replayProgress * replayDurationSeconds
    }

    var testingStatusText: String {
        usbBridgeStatus
    }

    var liveTrackDisplayName: String {
        if !liveTrackName.isEmpty {
            return liveTrackName
        }
        if let liveTrackId {
            return "Track #\(liveTrackId)"
        }
        return "Waiting track metadata"
    }

    var liveLapDisplayText: String {
        let lapText = liveLapNumber > 0 ? "Lap \(liveLapNumber)" : "Live Lap"
        let currentText = formattedDuration(liveCurrentLapTimeSec)
        let lastText = formattedDuration(liveLastLapTimeSec)

        if let currentText, let lastText {
            return "\(lapText) • \(currentText) • Last \(lastText)"
        }
        if let currentText {
            return "\(lapText) • \(currentText)"
        }
        return "\(lapText) • waiting timing"
    }

    var liveCompareCandidates: [LiveLapRecord] {
        liveValidCompletedLaps.sorted(by: { $0.lapNumber < $1.lapNumber })
    }

    var isUSBLiveMode: Bool {
        testingModeEnabled && testingFeedSource == .usbBridge
    }

    var liveBestLapSec: Double? {
        liveValidCompletedLaps.map(\.lapTimeSec).min()
    }

    var liveBestLapText: String {
        formatLapTime(seconds: liveBestLapSec)
    }

    var liveCompletedLapCount: Int {
        liveValidCompletedLaps.count
    }

    var liveConsistencyScore: Int {
        let samples = liveValidCompletedLaps.map(\.lapTimeSec)
        guard samples.count >= 2 else { return samples.isEmpty ? 0 : 100 }

        let mean = samples.reduce(0, +) / Double(samples.count)
        guard mean > 0 else { return 0 }

        let variance = samples
            .map { ($0 - mean) * ($0 - mean) }
            .reduce(0, +) / Double(samples.count)
        let std = sqrt(variance)
        let ratio = std / mean
        let score = Int((100.0 - ratio * 180.0).rounded())
        return min(max(score, 0), 100)
    }

    var liveLastUpdateText: String {
        guard let liveUpdatedAt else { return "No live packets yet" }
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM d, HH:mm:ss"
        return formatter.string(from: liveUpdatedAt)
    }

    var liveRecentInsights: [String] {
        let completed = liveValidCompletedLaps.sorted(by: { $0.lapNumber < $1.lapNumber })
        guard completed.count >= 2 else {
            return ["Waiting for at least two completed laps to compute real insights."]
        }

        let prev = completed[completed.count - 2]
        let last = completed[completed.count - 1]
        let lapDelta = last.lapTimeSec - prev.lapTimeSec

        let prevAvgSpeed = average(prev.telemetry.map(\.speed))
        let lastAvgSpeed = average(last.telemetry.map(\.speed))
        let speedDelta = lastAvgSpeed - prevAvgSpeed

        let prevBrake = average(prev.telemetry.map(\.brake)) * 100
        let lastBrake = average(last.telemetry.map(\.brake)) * 100
        let brakeDelta = lastBrake - prevBrake

        return [
            "Lap \(last.lapNumber) vs Lap \(prev.lapNumber): \(String(format: "%+.3fs", lapDelta)).",
            "Average speed \(String(format: "%+.1f km/h", speedDelta)) compared to previous lap.",
            "Average brake usage \(String(format: "%+.1f%%", brakeDelta)) compared to previous lap."
        ]
    }

    var liveLapsForDisplay: [LiveLapRecord] {
        var laps = liveValidCompletedLaps.sorted(by: { $0.lapNumber > $1.lapNumber })
        if let active = activeLiveLapRecord() {
            laps.insert(active, at: 0)
        }
        return laps
    }

    var liveDamageAlert: DamageAlert? {
        buildDamageAlert(from: liveDamage)
    }

    func openReplay() {
        selectedTab = .replay
    }

    func openCompare() {
        selectedTab = .compare
    }

    func setReplayProgress(_ value: Double) {
        replayProgress = value.clamped(to: 0.0...1.0)
        guard let sample = replaySample(at: replayProgress) else { return }
        liveTelemetrySample = sample
    }

    func skipReplay(by normalizedStep: Double) {
        setReplayProgress(replayProgress + normalizedStep)
    }

    func toggleReplay() {
        isReplayPlaying.toggle()
        guard testingModeEnabled, isReplayPlaying else { return }
        ensureUSBBridgeFileExists()
        readUSBBridgePackets()
    }

    func stopReplay() {
        isReplayPlaying = false
        replayProgress = 0.0
    }

    func pollUSBBridgeNow() {
        guard testingModeEnabled, testingFeedSource == .usbBridge else { return }
        ensureUSBBridgeFileExists()
        readUSBBridgePackets()
        if let last = liveTelemetrySeries.last {
            liveTelemetrySample = last
            liveClock = last.second
            syncReplayProgress(forSecond: last.second)
        }
    }

    func tickReplay(delta: Double) {
        guard isReplayPlaying else { return }
        guard testingModeEnabled else { return }
        tickUSBBridge(delta: delta)
    }

    func setTestingMode(_ enabled: Bool) {
        testingModeEnabled = enabled
        if enabled {
            resetLiveStream()
        } else {
            isReplayPlaying = false
            usbBridgeStatus = "USB live feed disabled"
        }
    }

    func setTestingFeedSource(_ source: TestingFeedSource) {
        testingFeedSource = source
        resetLiveStream()
    }

    func resetLiveStream() {
        liveClock = replayProgress * replayDurationSeconds
        packetAccumulator = 0
        usbReadOffset = 0
        usbPendingFragment = ""
        usbPacketsReceived = 0
        liveTelemetrySeries = []
        liveWorldPath = []
        liveTrackName = ""
        liveTrackId = nil
        liveTrackLengthMeters = nil
        liveLapNumber = 0
        liveCarPosition = nil
        liveTotalLaps = nil
        liveSector = nil
        liveCurrentLapTimeSec = nil
        liveLastLapTimeSec = nil
        liveDamage = .empty
        endDamageLiveActivity()
        clearLiveLapState()
        liveUpdatedAt = nil
        liveTelemetrySample = emptyTelemetrySample
        ensureUSBBridgeFileExists()
        syncUSBReaderToEnd()
        usbBridgeStatus = "USB bridge ready, Wi-Fi TCP :\(networkTelemetryPort) waiting packets"
    }

    func clearUSBBridgeLog() {
        ensureUSBBridgeFileExists()
        do {
            try Data().write(to: usbBridgeFileURL, options: .atomic)
            usbReadOffset = 0
            usbPendingFragment = ""
            usbPacketsReceived = 0
            liveTelemetrySeries = []
            liveWorldPath = []
            liveTrackName = ""
            liveTrackId = nil
            liveTrackLengthMeters = nil
            liveLapNumber = 0
            liveCarPosition = nil
            liveTotalLaps = nil
            liveSector = nil
            liveCurrentLapTimeSec = nil
            liveLastLapTimeSec = nil
            liveDamage = .empty
            endDamageLiveActivity()
            clearLiveLapState()
            liveTelemetrySample = emptyTelemetrySample
            liveUpdatedAt = nil
            usbBridgeStatus = "USB bridge log cleared, Wi-Fi TCP :\(networkTelemetryPort) waiting packets"
        } catch {
            usbBridgeStatus = "Failed to clear log: \(error.localizedDescription)"
        }
    }

    func replayChartSeries() -> [TelemetryPoint] {
        liveTelemetrySeries.isEmpty ? [liveTelemetrySample] : liveTelemetrySeries
    }

    func replayCurrentTelemetry() -> TelemetryPoint {
        if isUSBLiveMode {
            return liveTelemetrySample
        }
        return replaySample(at: replayProgress) ?? liveTelemetrySeries.last ?? emptyTelemetrySample
    }

    func formatReplayTime() -> String {
        let second = (isUSBLiveMode ? liveTelemetrySample.second : replaySample(at: replayProgress)?.second)
            ?? liveCurrentLapTimeSec
            ?? liveTelemetrySeries.last?.second
            ?? 0
        return formattedDuration(second) ?? "0:00.000"
    }

    private var usbBridgeFileURL: URL {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSTemporaryDirectory())
        return docs.appendingPathComponent("usb_live_stream.ndjson")
    }

    private func tickUSBBridge(delta: Double) {
        ensureUSBBridgeFileExists()
        packetAccumulator += delta

        let pollInterval = 1.0 / max(8.0, testingFeedHz)
        while packetAccumulator >= pollInterval {
            packetAccumulator -= pollInterval
            readUSBBridgePackets()
        }

        if let last = liveTelemetrySeries.last {
            liveTelemetrySample = last
            liveClock = last.second
            syncReplayProgress(forSecond: last.second)
        }
    }

    private func ensureUSBBridgeFileExists() {
        let url = usbBridgeFileURL
        let manager = FileManager.default
        let directory = url.deletingLastPathComponent()
        if !manager.fileExists(atPath: directory.path) {
            try? manager.createDirectory(at: directory, withIntermediateDirectories: true)
        }
        if !manager.fileExists(atPath: url.path) {
            manager.createFile(atPath: url.path, contents: nil)
        }
    }

    private func syncUSBReaderToEnd() {
        ensureUSBBridgeFileExists()
        do {
            let size = try FileManager.default.attributesOfItem(atPath: usbBridgeFileURL.path)[.size] as? NSNumber
            usbReadOffset = size?.uint64Value ?? 0
        } catch {
            usbReadOffset = 0
        }
    }

    private func readUSBBridgePackets() {
        do {
            let size = try FileManager.default.attributesOfItem(atPath: usbBridgeFileURL.path)[.size] as? NSNumber
            if let size, usbReadOffset > size.uint64Value {
                usbReadOffset = 0
                usbPendingFragment = ""
            }

            let handle = try FileHandle(forReadingFrom: usbBridgeFileURL)
            try handle.seek(toOffset: usbReadOffset)
            let data = handle.readDataToEndOfFile()
            try handle.close()

            guard !data.isEmpty else { return }

            usbReadOffset += UInt64(data.count)
            let chunk = usbPendingFragment + String(decoding: data, as: UTF8.self)
            let endedWithNewline = chunk.hasSuffix("\n")
            let rawLines = chunk.components(separatedBy: .newlines)

            let lines: [String]
            if endedWithNewline {
                usbPendingFragment = ""
                lines = rawLines
            } else {
                usbPendingFragment = rawLines.last ?? ""
                lines = Array(rawLines.dropLast())
            }

            var parsedCount = 0
            for line in lines {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.isEmpty { continue }
                if let sample = parseUSBBridgeLine(trimmed) {
                    appendLiveSample(sample)
                    parsedCount += 1
                }
            }

            if parsedCount > 0 {
                usbBridgeStatus = "Receiving USB stream (\(usbPacketsReceived) packets)"
            }
        } catch {
            usbBridgeStatus = "USB read failed: \(error.localizedDescription)"
        }
    }

    private func startWiFiTelemetryListener() {
        guard telemetryListener == nil, let port = NWEndpoint.Port(rawValue: networkTelemetryPort) else { return }

        do {
            let listener = try NWListener(using: .tcp, on: port)
            listener.service = NWListener.Service(name: "Asurada Telemetry", type: "_asurada-telemetry._tcp")
            listener.newConnectionHandler = { [weak self] connection in
                Task { @MainActor in
                    self?.acceptWiFiTelemetryConnection(connection)
                }
            }
            listener.stateUpdateHandler = { [weak self] state in
                Task { @MainActor in
                    self?.updateWiFiTelemetryListenerStatus(state)
                }
            }
            listener.start(queue: .global(qos: .userInitiated))
            telemetryListener = listener
        } catch {
            usbBridgeStatus = "Wi-Fi telemetry listener failed: \(error.localizedDescription)"
        }
    }

    private func updateWiFiTelemetryListenerStatus(_ state: NWListener.State) {
        switch state {
        case .ready:
            usbBridgeStatus = "Wi-Fi telemetry ready on TCP :\(networkTelemetryPort)"
        case .failed(let error):
            usbBridgeStatus = "Wi-Fi telemetry failed: \(error.localizedDescription)"
            telemetryListener?.cancel()
            telemetryListener = nil
        case .waiting(let error):
            usbBridgeStatus = "Wi-Fi telemetry waiting: \(error.localizedDescription)"
        default:
            break
        }
    }

    private func acceptWiFiTelemetryConnection(_ connection: NWConnection) {
        telemetryConnections.append(connection)
        usbBridgeStatus = "Wi-Fi telemetry connected"
        connection.stateUpdateHandler = { [weak self, weak connection] state in
            guard let connection else { return }
            Task { @MainActor in
                self?.updateWiFiTelemetryConnectionStatus(connection, state: state)
            }
        }
        connection.start(queue: .global(qos: .userInitiated))
        receiveWiFiTelemetry(from: connection)
    }

    private func updateWiFiTelemetryConnectionStatus(_ connection: NWConnection, state: NWConnection.State) {
        switch state {
        case .ready:
            usbBridgeStatus = "Wi-Fi telemetry receiving"
        case .failed(let error):
            removeWiFiTelemetryConnection(connection)
            usbBridgeStatus = "Wi-Fi telemetry disconnected: \(error.localizedDescription)"
        case .cancelled:
            removeWiFiTelemetryConnection(connection)
            usbBridgeStatus = "Wi-Fi telemetry ready on TCP :\(networkTelemetryPort)"
        default:
            break
        }
    }

    private func receiveWiFiTelemetry(from connection: NWConnection) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 8192) { [weak self, weak connection] data, _, isComplete, error in
            guard let connection else { return }
            let chunk = data.map { String(decoding: $0, as: UTF8.self) } ?? ""
            Task { @MainActor in
                self?.handleWiFiTelemetryChunk(
                    chunk,
                    from: connection,
                    isComplete: isComplete,
                    error: error
                )
            }
        }
    }

    private func handleWiFiTelemetryChunk(
        _ chunk: String,
        from connection: NWConnection,
        isComplete: Bool,
        error: NWError?
    ) {
        if !chunk.isEmpty {
            let connectionID = ObjectIdentifier(connection)
            let combined = (telemetryPendingFragments[connectionID] ?? "") + chunk
            let endedWithNewline = combined.hasSuffix("\n")
            let rawLines = combined.components(separatedBy: .newlines)

            let lines: [String]
            if endedWithNewline {
                telemetryPendingFragments[connectionID] = ""
                lines = rawLines
            } else {
                telemetryPendingFragments[connectionID] = rawLines.last ?? ""
                lines = Array(rawLines.dropLast())
            }

            var parsedCount = 0
            for line in lines {
                let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
                if trimmed.isEmpty { continue }
                if let sample = parseUSBBridgeLine(trimmed) {
                    appendLiveSample(sample)
                    parsedCount += 1
                }
            }

            if parsedCount > 0 {
                usbBridgeStatus = "Receiving Wi-Fi stream (\(usbPacketsReceived) packets)"
            }
        }

        if isComplete || error != nil {
            removeWiFiTelemetryConnection(connection)
            if let error {
                usbBridgeStatus = "Wi-Fi telemetry stopped: \(error.localizedDescription)"
            }
            return
        }

        receiveWiFiTelemetry(from: connection)
    }

    private func removeWiFiTelemetryConnection(_ connection: NWConnection) {
        telemetryPendingFragments.removeValue(forKey: ObjectIdentifier(connection))
        telemetryConnections.removeAll { $0 === connection }
    }

    private func parseUSBBridgeLine(_ line: String) -> TelemetryPoint? {
        if line.hasPrefix("{"), let sample = parseJSONUSBLine(line) {
            return sample
        }
        return parseCSVUSBLine(line)
    }

    private func parseJSONUSBLine(_ line: String) -> TelemetryPoint? {
        guard
            let data = line.data(using: .utf8),
            let object = try? JSONSerialization.jsonObject(with: data),
            let json = object as? [String: Any]
        else {
            return nil
        }

        let second = extractNumber(from: json, keys: ["second", "time", "t", "timestampSec", "timestamp_s", "timestampMs", "timestamp_ms", "timestamp", "ts"])
        let speed = extractNumber(from: json, keys: ["speed", "speedKph", "speed_kph", "v", "velocity"])
        let throttle = extractNumber(from: json, keys: ["throttle", "throttlePct", "throttle_pct", "gas", "accel"])
        let brake = extractNumber(from: json, keys: ["brake", "brakePct", "brake_pct"])
        let delta = extractNumber(from: json, keys: ["delta", "lapDelta", "timeDelta", "dt"]) ?? 0
        let steer = extractNumber(from: json, keys: ["steer", "steering", "steeringInput"]) ?? 0
        let gear = extractInt(from: json, keys: ["gear", "currentGear"]) ?? 0
        let rpm = extractInt(from: json, keys: ["rpm", "engineRPM", "engineRpm"]) ?? 0
        let drs = extractBool(from: json, keys: ["drs", "drsOpen", "drsActive"]) ?? false
        let revLights = extractInt(from: json, keys: ["revLightsPercent", "rev_lights_percent", "revLights"]) ?? 0

        guard let speed else { return nil }

        updateLiveUSBMetadata(from: json)
        updateLiveDamage(from: json)

        let resolvedSecond = resolveSecond(secondRaw: second)
        return TelemetryPoint(
            second: resolvedSecond,
            speed: speed,
            throttle: normalizePedal(throttle),
            brake: normalizePedal(brake),
            delta: delta,
            steer: steer.clamped(to: -1...1),
            gear: gear,
            rpm: max(0, rpm),
            drs: drs,
            revLightsPercent: revLights.clamped(to: 0...100)
        )
    }

    private func parseCSVUSBLine(_ line: String) -> TelemetryPoint? {
        let tokens = line.split(separator: ",").map { String($0).trimmingCharacters(in: .whitespaces) }
        guard tokens.count >= 4 else { return nil }

        let second = Double(tokens[0])
        let speed = Double(tokens[1])
        let throttle = Double(tokens[2])
        let brake = Double(tokens[3])
        let delta = tokens.count > 4 ? Double(tokens[4]) : nil

        guard let speed else { return nil }

        return TelemetryPoint(
            second: resolveSecond(secondRaw: second),
            speed: speed,
            throttle: normalizePedal(throttle),
            brake: normalizePedal(brake),
            delta: delta ?? 0,
            steer: 0,
            gear: 0,
            rpm: 0,
            drs: false,
            revLightsPercent: 0
        )
    }

    private func appendLiveSample(_ sample: TelemetryPoint) {
        liveTelemetrySample = sample
        liveTelemetrySeries.append(sample)
        if liveTelemetrySeries.count > maxLiveSampleCount {
            liveTelemetrySeries.removeFirst(liveTelemetrySeries.count - maxLiveSampleCount)
        }
        appendLiveLapSample(sample)
        liveUpdatedAt = Date()
        usbPacketsReceived += 1
    }

    private func syncReplayProgress(forSecond second: Double) {
        let duration = max(1.0, replayDurationSeconds)
        var normalized = (second / duration).truncatingRemainder(dividingBy: 1.0)
        if normalized < 0 { normalized += 1.0 }
        replayProgress = normalized
    }

    private func replaySample(at progress: Double) -> TelemetryPoint? {
        guard let last = liveTelemetrySeries.last, !liveTelemetrySeries.isEmpty else {
            return nil
        }
        let targetSecond = progress.clamped(to: 0...1) * max(1.0, last.second)
        return liveTelemetrySeries.min(by: { abs($0.second - targetSecond) < abs($1.second - targetSecond) })
    }

    private func resolveSecond(secondRaw: Double?) -> Double {
        guard let secondRaw else {
            return liveTelemetrySeries.last.map { $0.second + 1.0 / max(8.0, testingFeedHz) } ?? 0
        }
        if secondRaw > 1_000_000 {
            return secondRaw / 1_000
        }
        return secondRaw
    }

    private func normalizePedal(_ value: Double?) -> Double {
        guard let value else { return 0 }
        if value > 1.0 {
            return (value / 100.0).clamped(to: 0...1)
        }
        return value.clamped(to: 0...1)
    }

    private func extractNumber(from json: [String: Any], keys: [String]) -> Double? {
        for key in keys {
            guard let raw = json[key] else { continue }
            if let value = raw as? Double { return value }
            if let value = raw as? Int { return Double(value) }
            if let value = raw as? NSNumber { return value.doubleValue }
            if let text = raw as? String, let value = Double(text) { return value }
        }
        return nil
    }

    private func extractInt(from json: [String: Any], keys: [String]) -> Int? {
        for key in keys {
            guard let raw = json[key] else { continue }
            if let value = raw as? Int { return value }
            if let value = raw as? Double { return Int(value) }
            if let value = raw as? NSNumber { return value.intValue }
            if let text = raw as? String, let value = Int(text) { return value }
        }
        return nil
    }

    private func extractBool(from json: [String: Any], keys: [String]) -> Bool? {
        for key in keys {
            guard let raw = json[key] else { continue }
            if let value = raw as? Bool { return value }
            if let value = raw as? Int { return value != 0 }
            if let value = raw as? Double { return abs(value) > 0.0001 }
            if let value = raw as? NSNumber { return value.boolValue }
            if let text = raw as? String {
                let normalized = text.lowercased()
                if ["1", "true", "yes", "open", "active", "on"].contains(normalized) { return true }
                if ["0", "false", "no", "closed", "inactive", "off"].contains(normalized) { return false }
            }
        }
        return nil
    }

    private func extractNumberArray(from json: [String: Any], keys: [String]) -> [Double]? {
        for key in keys {
            guard let raw = json[key] else { continue }
            if let values = raw as? [Double] { return values }
            if let values = raw as? [Int] { return values.map(Double.init) }
            if let values = raw as? [NSNumber] { return values.map(\.doubleValue) }
            if let values = raw as? [Any] {
                let parsed = values.compactMap { item -> Double? in
                    if let value = item as? Double { return value }
                    if let value = item as? Int { return Double(value) }
                    if let value = item as? NSNumber { return value.doubleValue }
                    if let text = item as? String { return Double(text) }
                    return nil
                }
                if !parsed.isEmpty { return parsed }
            }
            if let text = raw as? String {
                let parsed = text
                    .split { $0 == "," || $0 == " " || $0 == ";" }
                    .compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
                if !parsed.isEmpty { return parsed }
            }
        }
        return nil
    }

    private func extractIntArray(from json: [String: Any], keys: [String]) -> [Int]? {
        extractNumberArray(from: json, keys: keys)?.map { Int($0.rounded()) }
    }

    private func updateLiveUSBMetadata(from json: [String: Any]) {
        if let trackName = json["trackName"] as? String, !trackName.isEmpty {
            liveTrackName = trackName
        }
        if let trackId = extractInt(from: json, keys: ["trackId"]) {
            liveTrackId = trackId
        }
        if let trackLength = extractInt(from: json, keys: ["trackLengthM", "trackLengthMeters"]) {
            liveTrackLengthMeters = trackLength
        }
        if let lapNumber = extractInt(from: json, keys: ["lapNumber", "liveLapNumber", "currentLapNum"]) {
            liveLapNumber = max(0, lapNumber)
        }
        if let carPosition = extractInt(from: json, keys: ["carPosition", "position", "racePosition"]) {
            liveCarPosition = max(1, carPosition)
        }
        if let totalLaps = extractInt(from: json, keys: ["totalLaps", "raceLaps"]) {
            liveTotalLaps = max(0, totalLaps)
        }
        if let sector = extractInt(from: json, keys: ["sector", "currentSector"]) {
            liveSector = max(0, sector)
        }
        if let currentLapTime = extractNumber(from: json, keys: ["currentLapTimeSec", "lapTimeSec"]), currentLapTime > 0.001 {
            liveCurrentLapTimeSec = currentLapTime
        } else if let sessionTime = extractNumber(from: json, keys: ["second", "time", "t"]), sessionTime > 0 {
            liveCurrentLapTimeSec = sessionTime
        }
        if let lastLapTime = extractNumber(from: json, keys: ["lastLapTimeSec"]), lastLapTime > 0.001 {
            liveLastLapTimeSec = lastLapTime
        }

        let worldX = extractNumber(from: json, keys: ["worldX", "x"])
        let worldY = extractNumber(from: json, keys: ["worldY", "worldZ", "y", "z"])
        if let worldX, let worldY {
            appendWorldPoint(x: worldX, y: worldY)
        }
    }

    private func updateLiveDamage(from json: [String: Any]) {
        var next = liveDamage
        var didUpdate = false

        if let values = extractNumberArray(from: json, keys: ["tyresWearPct", "tyres_wear_pct", "tyreWearPct", "tyreWear"]) {
            next.tyresWearPct = Array(values.prefix(4))
            didUpdate = true
        }
        if let values = extractIntArray(from: json, keys: ["tyresDamagePct", "tyres_damage_pct", "tyreDamagePct", "tyreDamage"]) {
            next.tyresDamagePct = Array(values.prefix(4))
            didUpdate = true
        }
        if let values = extractIntArray(from: json, keys: ["brakesDamagePct", "brakes_damage_pct", "brakeDamagePct", "brakeDamage"]) {
            next.brakesDamagePct = Array(values.prefix(4))
            didUpdate = true
        }
        if let values = extractIntArray(from: json, keys: ["tyreBlistersPct", "tyre_blisters_pct", "tyreBlisterPct", "tyreBlisters"]) {
            next.tyreBlistersPct = Array(values.prefix(4))
            didUpdate = true
        }

        if let value = extractInt(from: json, keys: ["frontLeftWingDamagePct", "front_left_wing_damage_pct"]) {
            next.frontLeftWingDamagePct = value.clamped(to: 0...100)
            didUpdate = true
        }
        if let value = extractInt(from: json, keys: ["frontRightWingDamagePct", "front_right_wing_damage_pct"]) {
            next.frontRightWingDamagePct = value.clamped(to: 0...100)
            didUpdate = true
        }
        if let value = extractInt(from: json, keys: ["rearWingDamagePct", "rear_wing_damage_pct"]) {
            next.rearWingDamagePct = value.clamped(to: 0...100)
            didUpdate = true
        }
        if let value = extractInt(from: json, keys: ["floorDamagePct", "floor_damage_pct"]) {
            next.floorDamagePct = value.clamped(to: 0...100)
            didUpdate = true
        }
        if let value = extractInt(from: json, keys: ["diffuserDamagePct", "diffuser_damage_pct"]) {
            next.diffuserDamagePct = value.clamped(to: 0...100)
            didUpdate = true
        }
        if let value = extractInt(from: json, keys: ["sidepodDamagePct", "sidepod_damage_pct"]) {
            next.sidepodDamagePct = value.clamped(to: 0...100)
            didUpdate = true
        }
        if let value = extractInt(from: json, keys: ["gearboxDamagePct", "gearbox_damage_pct"]) {
            next.gearboxDamagePct = value.clamped(to: 0...100)
            didUpdate = true
        }
        if let value = extractInt(from: json, keys: ["engineDamagePct", "engine_damage_pct"]) {
            next.engineDamagePct = value.clamped(to: 0...100)
            didUpdate = true
        }

        if let value = extractBool(from: json, keys: ["drsFault", "drs_fault"]) {
            next.drsFault = value
            didUpdate = true
        }
        if let value = extractBool(from: json, keys: ["ersFault", "ers_fault"]) {
            next.ersFault = value
            didUpdate = true
        }
        if let value = extractBool(from: json, keys: ["engineBlown", "engine_blown"]) {
            next.engineBlown = value
            didUpdate = true
        }
        if let value = extractBool(from: json, keys: ["engineSeized", "engine_seized"]) {
            next.engineSeized = value
            didUpdate = true
        }

        if didUpdate {
            liveDamage = next
            syncDamageLiveActivity()
        }
    }

    private func buildDamageAlert(from damage: CarDamageState) -> DamageAlert? {
        guard damage.hasTelemetry else { return nil }

        let tyreLabels = ["RL", "RR", "FL", "FR"]
        var warnings: [DamageZoneWarning] = []

        for (index, value) in damage.tyresWearPct.enumerated() where value >= tyreWearCriticalPct {
            let label = index < tyreLabels.count ? "\(tyreLabels[index]) TYRE WEAR" : "TYRE \(index + 1) WEAR"
            warnings.append(DamageZoneWarning(id: "tyre-wear-\(index)", label: label, valuePct: value, kind: .tyreWear))
        }

        for (index, value) in damage.tyresDamagePct.enumerated() where Double(value) >= tyreDamageCriticalPct {
            let label = index < tyreLabels.count ? "\(tyreLabels[index]) TYRE DAMAGE" : "TYRE \(index + 1) DAMAGE"
            warnings.append(DamageZoneWarning(id: "tyre-damage-\(index)", label: label, valuePct: Double(value), kind: .tyreDamage))
        }

        for (index, value) in damage.tyreBlistersPct.enumerated() where Double(value) >= tyreDamageCriticalPct {
            let label = index < tyreLabels.count ? "\(tyreLabels[index]) BLISTER" : "TYRE \(index + 1) BLISTER"
            warnings.append(DamageZoneWarning(id: "tyre-blister-\(index)", label: label, valuePct: Double(value), kind: .tyreDamage))
        }

        let structuralItems: [(String, Int)] = [
            ("FL WING", damage.frontLeftWingDamagePct),
            ("FR WING", damage.frontRightWingDamagePct),
            ("REAR WING", damage.rearWingDamagePct),
            ("FLOOR", damage.floorDamagePct),
            ("DIFFUSER", damage.diffuserDamagePct),
            ("SIDEPOD", damage.sidepodDamagePct),
            ("GEARBOX", damage.gearboxDamagePct),
            ("ENGINE", damage.engineDamagePct)
        ]

        for item in structuralItems where Double(item.1) >= structuralDamageCriticalPct {
            warnings.append(DamageZoneWarning(
                id: "structure-\(item.0.lowercased().replacingOccurrences(of: " ", with: "-"))",
                label: item.0,
                valuePct: Double(item.1),
                kind: .structure
            ))
        }

        let faults: [(String, Bool)] = [
            ("DRS FAULT", damage.drsFault),
            ("ERS FAULT", damage.ersFault),
            ("ENGINE BLOWN", damage.engineBlown),
            ("ENGINE SEIZED", damage.engineSeized)
        ]

        for fault in faults where fault.1 {
            warnings.append(DamageZoneWarning(
                id: "fault-\(fault.0.lowercased().replacingOccurrences(of: " ", with: "-"))",
                label: fault.0,
                valuePct: 100,
                kind: .fault
            ))
        }

        warnings.sort { lhs, rhs in
            if lhs.valuePct != rhs.valuePct {
                return lhs.valuePct > rhs.valuePct
            }
            let lhsPriority = damageWarningPriority(lhs.kind)
            let rhsPriority = damageWarningPriority(rhs.kind)
            if lhsPriority != rhsPriority {
                return lhsPriority > rhsPriority
            }
            return lhs.label < rhs.label
        }

        guard !warnings.isEmpty else { return nil }

        let maxSeverity = warnings.map(\.valuePct).max() ?? 0
        let title: String
        switch warnings.first?.kind {
        case .fault:
            title = "CRITICAL CAR DAMAGE"
        case .structure:
            title = "STRUCTURE LIMIT EXCEEDED"
        case .tyreWear, .tyreDamage:
            title = "TYRE LIMIT EXCEEDED"
        case nil:
            title = "CAR DAMAGE"
        }

        let id = warnings
            .map { "\($0.id):\(Int($0.valuePct.rounded()))" }
            .joined(separator: "|")
        let subtitle = "\(warnings.count) mapped zone\(warnings.count == 1 ? "" : "s") over limit"

        return DamageAlert(
            id: id,
            title: title,
            subtitle: subtitle,
            maxSeverityPct: maxSeverity,
            warnings: warnings,
            damage: damage
        )
    }

    private func damageWarningPriority(_ kind: DamageWarningKind) -> Int {
        switch kind {
        case .fault:
            return 3
        case .structure:
            return 2
        case .tyreDamage, .tyreWear:
            return 1
        }
    }

    private func syncDamageLiveActivity() {
        let activitiesEnabled = ActivityAuthorizationInfo().areActivitiesEnabled
        liveActivityLogger.info("sync requested enabled=\(activitiesEnabled) activeCount=\(Activity<RaceDamageActivityAttributes>.activities.count)")
        guard activitiesEnabled else { return }

        guard let alert = buildDamageAlert(from: liveDamage) else {
            liveActivityLogger.info("ending activity because no active damage alert")
            endDamageLiveActivity()
            return
        }

        let state = makeLiveActivityState(from: alert)
        guard state != lastLiveActivityState else { return }

        let expansionKey = liveActivityExpansionKey(from: alert)
        let shouldExpand = expansionKey != lastLiveActivityExpansionKey
        let isHoldingExpandedIsland = liveActivityExpandedUntil.map { Date() < $0 } ?? false

        lastLiveActivityState = state
        lastLiveActivityExpansionKey = expansionKey

        if shouldExpand {
            liveActivityExpandedUntil = Date().addingTimeInterval(5)
            presentForegroundDamageIsland(state: state)
            liveActivityCollapseTask?.cancel()
            liveActivityCollapseTask = Task { [state] in
                try? await Task.sleep(nanoseconds: 5_000_000_000)
                guard !Task.isCancelled else { return }
                await AppState.requestOrUpdateDamageLiveActivity(state: state, presentsAlert: false)
            }
        } else if isHoldingExpandedIsland {
            foregroundDamageIslandState = state
            return
        } else {
            foregroundDamageIslandState = state
        }

        liveActivityTask?.cancel()
        liveActivityTask = Task { [state, shouldExpand] in
            await AppState.requestOrUpdateDamageLiveActivity(state: state, presentsAlert: shouldExpand)
        }
    }

    private func endDamageLiveActivity() {
        lastLiveActivityState = nil
        lastLiveActivityExpansionKey = nil
        liveActivityExpandedUntil = nil
        liveActivityTask?.cancel()
        liveActivityCollapseTask?.cancel()
        foregroundDamageIslandToken = UUID()
        foregroundDamageIslandState = nil
        foregroundDamageIslandExpanded = false
        liveActivityTask = Task {
            await AppState.endDamageLiveActivities()
        }
    }

    private func presentForegroundDamageIsland(state: RaceDamageActivityAttributes.ContentState) {
        let token = UUID()
        foregroundDamageIslandToken = token
        foregroundDamageIslandState = state
        foregroundDamageIslandExpanded = true

        DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
            guard let self, self.foregroundDamageIslandToken == token else { return }
            self.foregroundDamageIslandExpanded = false
        }
    }

    private func liveActivityExpansionKey(from alert: DamageAlert) -> String {
        alert.warnings
            .map(\.id)
            .sorted()
            .joined(separator: "|")
    }

    private func makeLiveActivityState(from alert: DamageAlert) -> RaceDamageActivityAttributes.ContentState {
        let damage = alert.damage
        let tyreWearMax = damage.tyresWearPct.max() ?? 0
        let tyreDamageMax = Double(damage.tyresDamagePct.max() ?? 0)
        let tyreBlisterMax = Double(damage.tyreBlistersPct.max() ?? 0)
        let brakeDamageMax = Double(damage.brakesDamagePct.max() ?? 0)
        let structuralMax = Double(damage.structuralValues.max() ?? 0)
        let tyreMax = max(tyreWearMax, tyreDamageMax, tyreBlisterMax, brakeDamageMax)

        return RaceDamageActivityAttributes.ContentState(
            title: alert.title,
            primaryZone: alert.warnings.first?.label ?? "CAR DAMAGE",
            trackName: liveTrackDisplayName,
            lapText: liveActivityLapText,
            severityPct: Int(alert.maxSeverityPct.rounded()).clamped(to: 0...100),
            affectedCount: alert.warnings.count,
            tyreWearMaxPct: Int(tyreMax.rounded()).clamped(to: 0...100),
            structuralMaxPct: Int(structuralMax.rounded()).clamped(to: 0...100),
            frontLeftTyreCritical: isTyreCritical(index: 2, damage: damage),
            frontRightTyreCritical: isTyreCritical(index: 3, damage: damage),
            rearLeftTyreCritical: isTyreCritical(index: 0, damage: damage),
            rearRightTyreCritical: isTyreCritical(index: 1, damage: damage),
            frontWingCritical: Double(max(damage.frontLeftWingDamagePct, damage.frontRightWingDamagePct)) >= structuralDamageCriticalPct,
            rearWingCritical: Double(damage.rearWingDamagePct) >= structuralDamageCriticalPct,
            floorCritical: Double(damage.floorDamagePct) >= structuralDamageCriticalPct,
            diffuserCritical: Double(damage.diffuserDamagePct) >= structuralDamageCriticalPct,
            sidepodCritical: Double(damage.sidepodDamagePct) >= structuralDamageCriticalPct,
            engineCritical: Double(max(damage.engineDamagePct, damage.gearboxDamagePct)) >= structuralDamageCriticalPct,
            hasFault: damage.drsFault || damage.ersFault || damage.engineBlown || damage.engineSeized
        )
    }

    private var liveActivityLapText: String {
        guard liveLapNumber > 0 else { return "LIVE" }
        if let total = liveTotalLaps, total > 0 {
            return "L\(liveLapNumber)/\(total)"
        }
        return "L\(liveLapNumber)"
    }

    private func isTyreCritical(index: Int, damage: CarDamageState) -> Bool {
        tyreDouble(damage.tyresWearPct, index: index) >= tyreWearCriticalPct
            || Double(tyreInt(damage.tyresDamagePct, index: index)) >= tyreDamageCriticalPct
            || Double(tyreInt(damage.tyreBlistersPct, index: index)) >= tyreDamageCriticalPct
            || Double(tyreInt(damage.brakesDamagePct, index: index)) >= tyreDamageCriticalPct
    }

    private func tyreDouble(_ values: [Double], index: Int) -> Double {
        index < values.count ? values[index] : 0
    }

    private func tyreInt(_ values: [Int], index: Int) -> Int {
        index < values.count ? values[index] : 0
    }

    private static func requestOrUpdateDamageLiveActivity(
        state: RaceDamageActivityAttributes.ContentState,
        presentsAlert: Bool
    ) async {
        let content = ActivityContent(state: state, staleDate: Date().addingTimeInterval(300))

        if let activity = Activity<RaceDamageActivityAttributes>.activities.first {
            liveActivityLogger.info("updating existing activity id=\(activity.id) primaryZone=\(state.primaryZone) severity=\(state.severityPct)")
            if presentsAlert {
                await activity.update(content, alertConfiguration: liveActivityAlertConfiguration(for: state))
            } else {
                await activity.update(content)
            }
            return
        }

        do {
            let activity = try Activity.request(
                attributes: RaceDamageActivityAttributes(carName: "ASURADA"),
                content: content,
                pushType: nil
            )
            liveActivityLogger.info("requested activity id=\(activity.id) primaryZone=\(state.primaryZone) severity=\(state.severityPct)")
            if presentsAlert {
                await activity.update(content, alertConfiguration: liveActivityAlertConfiguration(for: state))
            } else {
                await activity.update(content)
            }
        } catch {
            // Live Activities can be disabled by the system or user; the in-app feed should keep running.
            liveActivityLogger.error("request failed: \(error.localizedDescription)")
        }
    }

    private static func liveActivityAlertConfiguration(
        for state: RaceDamageActivityAttributes.ContentState
    ) -> AlertConfiguration {
        AlertConfiguration(
            title: "\(state.title)",
            body: "\(state.primaryZone) \(state.severityPct)%",
            sound: .default
        )
    }

    private static func endDamageLiveActivities() async {
        for activity in Activity<RaceDamageActivityAttributes>.activities {
            liveActivityLogger.info("ending activity id=\(activity.id)")
            await activity.end(nil, dismissalPolicy: .immediate)
        }
    }

    private func appendWorldPoint(x: Double, y: Double) {
        guard x.isFinite, y.isFinite else { return }
        let point = WorldPoint(x: x, y: y)

        if let last = liveWorldPath.last {
            let dx = point.x - last.x
            let dy = point.y - last.y
            if (dx * dx + dy * dy) < 0.25 {
                return
            }
        }

        liveWorldPath.append(point)
        if liveWorldPath.count > maxLiveWorldPointCount {
            liveWorldPath.removeFirst(liveWorldPath.count - maxLiveWorldPointCount)
        }
    }

    private func appendLiveLapSample(_ sample: TelemetryPoint) {
        let lapNumber = max(0, liveLapNumber)
        guard lapNumber > 0 else { return }

        if buildingLapNumber == nil {
            buildingLapNumber = lapNumber
            buildingLapSamples = []
            buildingLapMaxCurrentTimeSec = 0
        }

        if let current = liveCurrentLapTimeSec, current > 0.001 {
            buildingLapMaxCurrentTimeSec = max(buildingLapMaxCurrentTimeSec, current)
        }

        if buildingLapNumber != lapNumber {
            finalizeBuildingLap()
            buildingLapNumber = lapNumber
            buildingLapSamples = []
            buildingLapMaxCurrentTimeSec = 0
            if let current = liveCurrentLapTimeSec, current > 0.001 {
                buildingLapMaxCurrentTimeSec = current
            }
        }

        buildingLapSamples.append(sample)
        if buildingLapSamples.count > maxLiveLapSampleCount {
            buildingLapSamples.removeFirst(buildingLapSamples.count - maxLiveLapSampleCount)
        }
    }

    private func finalizeBuildingLap() {
        guard
            let lapNumber = buildingLapNumber,
            buildingLapSamples.count >= minLiveLapSampleCount
        else { return }

        let firstSecond = buildingLapSamples.first?.second ?? 0
        let lastSecond = buildingLapSamples.last?.second ?? firstSecond
        let elapsedFromSamples = max(0, lastSecond - firstSecond)
        let resolvedTime = max(elapsedFromSamples, buildingLapMaxCurrentTimeSec, liveLastLapTimeSec ?? 0)

        let normalizedSamples = buildingLapSamples.map { sample in
            TelemetryPoint(
                second: max(0, sample.second - firstSecond),
                speed: sample.speed,
                throttle: sample.throttle,
                brake: sample.brake,
                delta: sample.delta,
                steer: sample.steer,
                gear: sample.gear,
                rpm: sample.rpm,
                drs: sample.drs,
                revLightsPercent: sample.revLightsPercent
            )
        }

        let record = LiveLapRecord(
            id: UUID(),
            lapNumber: lapNumber,
            lapTimeSec: resolvedTime,
            telemetry: normalizedSamples,
            isComplete: true
        )

        guard isValidLapDuration(record.lapTimeSec) else { return }

        if let index = liveCompletedLaps.firstIndex(where: { $0.lapNumber == lapNumber }) {
            liveCompletedLaps[index] = record
        } else {
            liveCompletedLaps.append(record)
        }
        liveCompletedLaps.sort(by: { $0.lapNumber < $1.lapNumber })
        if liveCompletedLaps.count > 8 {
            liveCompletedLaps.removeFirst(liveCompletedLaps.count - 8)
        }
    }

    private func activeLiveLapRecord() -> LiveLapRecord? {
        guard
            let lapNumber = buildingLapNumber,
            buildingLapSamples.count >= minLiveLapSampleCount
        else {
            return nil
        }

        let firstSecond = buildingLapSamples.first?.second ?? 0
        let lastSecond = buildingLapSamples.last?.second ?? firstSecond
        let elapsedFromSamples = max(0, lastSecond - firstSecond)
        let resolvedTime = max(elapsedFromSamples, buildingLapMaxCurrentTimeSec, liveCurrentLapTimeSec ?? 0)

        let normalizedSamples = buildingLapSamples.map { sample in
            TelemetryPoint(
                second: max(0, sample.second - firstSecond),
                speed: sample.speed,
                throttle: sample.throttle,
                brake: sample.brake,
                delta: sample.delta,
                steer: sample.steer,
                gear: sample.gear,
                rpm: sample.rpm,
                drs: sample.drs,
                revLightsPercent: sample.revLightsPercent
            )
        }

        return LiveLapRecord(
            id: UUID(uuidString: "00000000-0000-0000-0000-\(String(format: "%012d", lapNumber))") ?? UUID(),
            lapNumber: lapNumber,
            lapTimeSec: resolvedTime,
            telemetry: normalizedSamples,
            isComplete: false
        )
    }

    private func clearLiveLapState() {
        liveCompletedLaps = []
        buildingLapNumber = nil
        buildingLapSamples = []
        buildingLapMaxCurrentTimeSec = 0
    }

    func formatLapTime(seconds: Double?) -> String {
        formattedDuration(seconds) ?? "--:--.---"
    }

    private var liveValidCompletedLaps: [LiveLapRecord] {
        liveCompletedLaps.filter { isValidLapDuration($0.lapTimeSec) }
    }

    private func average(_ values: [Double]) -> Double {
        guard !values.isEmpty else { return 0 }
        return values.reduce(0, +) / Double(values.count)
    }

    private func isValidLapDuration(_ seconds: Double) -> Bool {
        seconds.isFinite && seconds >= minValidLapDurationSec && seconds <= maxValidLapDurationSec
    }

    private func formattedDuration(_ seconds: Double?) -> String? {
        guard let seconds, seconds > 0 else { return nil }
        let totalMillis = Int((seconds * 1000).rounded())
        let minutes = totalMillis / 60_000
        let secs = (totalMillis % 60_000) / 1000
        let millis = totalMillis % 1000
        return String(format: "%d:%02d.%03d", minutes, secs, millis)
    }
}

private extension Comparable {
    func clamped(to range: ClosedRange<Self>) -> Self {
        min(max(self, range.lowerBound), range.upperBound)
    }
}

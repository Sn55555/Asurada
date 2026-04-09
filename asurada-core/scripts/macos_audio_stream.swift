import AVFoundation
import Foundation

struct StreamEvent: Codable {
    let type: String
    let status: String?
    let started_at_ms: Int64?
    let ended_at_ms: Int64?
    let duration_ms: Int64?
    let rms: Float?
    let audio_base64: String?
    let metadata: [String: String]
}

final class StreamingAudioCapture {
    private let listenTimeout: TimeInterval
    private let silenceTimeout: TimeInterval
    private let levelThreshold: Float
    private let audioEngine = AVAudioEngine()
    private let targetFormat = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 16000, channels: 1, interleaved: true)!
    private var converter: AVAudioConverter?
    private var continuation: CheckedContinuation<Void, Never>?
    private var finishTimer: DispatchSourceTimer?
    private var silenceWorkItem: DispatchWorkItem?
    private var hasFinished = false
    private var hasSpeech = false
    private var startedAtMs: Int64 = 0

    init(listenTimeout: TimeInterval, silenceTimeout: TimeInterval, levelThreshold: Float) {
        self.listenTimeout = listenTimeout
        self.silenceTimeout = silenceTimeout
        self.levelThreshold = levelThreshold
    }

    func run() async {
        let micAllowed = await requestMicrophoneAccess()
        guard micAllowed else {
            emit(
                StreamEvent(
                    type: "end",
                    status: "microphone_denied",
                    started_at_ms: nil,
                    ended_at_ms: nowMs(),
                    duration_ms: 0,
                    rms: nil,
                    audio_base64: nil,
                    metadata: ["microphone_access": "denied"]
                )
            )
            return
        }

        startedAtMs = nowMs()
        emit(
            StreamEvent(
                type: "start",
                status: "listening",
                started_at_ms: startedAtMs,
                ended_at_ms: nil,
                duration_ms: nil,
                rms: nil,
                audio_base64: nil,
                metadata: [:]
            )
        )
        await withCheckedContinuation { continuation in
            self.continuation = continuation
            self.startCapture()
        }
    }

    private func startCapture() {
        let inputNode = audioEngine.inputNode
        let inputFormat = inputNode.outputFormat(forBus: 0)
        converter = AVAudioConverter(from: inputFormat, to: targetFormat)

        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 2048, format: inputFormat) { [weak self] buffer, _ in
            self?.handle(buffer: buffer)
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            finish(status: "audio_engine_error", metadata: ["error": error.localizedDescription])
            return
        }

        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global())
        timer.schedule(deadline: .now() + listenTimeout)
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            if self.hasSpeech {
                self.finish(status: "recorded_timeout", metadata: ["timeout": "listen_timeout"])
            } else {
                self.finish(status: "timeout_no_speech", metadata: ["timeout": "listen_timeout"])
            }
        }
        timer.resume()
        finishTimer = timer
    }

    private func handle(buffer: AVAudioPCMBuffer) {
        guard !hasFinished else { return }
        guard let converter else { return }

        let ratio = targetFormat.sampleRate / max(buffer.format.sampleRate, 1.0)
        let estimatedFrameCapacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 64
        guard let convertedBuffer = AVAudioPCMBuffer(pcmFormat: targetFormat, frameCapacity: max(estimatedFrameCapacity, 1)) else {
            return
        }

        var didProvideInput = false
        var convertError: NSError?
        let status = converter.convert(to: convertedBuffer, error: &convertError) { _, outStatus in
            if didProvideInput {
                outStatus.pointee = .noDataNow
                return nil
            }
            didProvideInput = true
            outStatus.pointee = .haveData
            return buffer
        }

        if let convertError {
            finish(status: "audio_convert_error", metadata: ["error": convertError.localizedDescription])
            return
        }
        if status == .error || convertedBuffer.frameLength == 0 {
            return
        }

        let pcmBytes = extractPCMData(from: convertedBuffer)
        if pcmBytes.isEmpty {
            return
        }
        let rms = computeRms(bytes: pcmBytes)
        if rms >= levelThreshold {
            hasSpeech = true
            resetSilenceTimer()
        }

        emit(
            StreamEvent(
                type: "chunk",
                status: nil,
                started_at_ms: nil,
                ended_at_ms: nil,
                duration_ms: nil,
                rms: rms,
                audio_base64: pcmBytes.base64EncodedString(),
                metadata: [:]
            )
        )
    }

    private func resetSilenceTimer() {
        silenceWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            self?.finish(status: "recorded", metadata: ["timeout": "silence_timeout"])
        }
        silenceWorkItem = workItem
        DispatchQueue.global().asyncAfter(deadline: .now() + silenceTimeout, execute: workItem)
    }

    private func finish(status: String, metadata: [String: String]) {
        guard !hasFinished else { return }
        hasFinished = true
        silenceWorkItem?.cancel()
        finishTimer?.cancel()
        finishTimer = nil
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)

        let endedAt = nowMs()
        emit(
            StreamEvent(
                type: "end",
                status: status,
                started_at_ms: startedAtMs,
                ended_at_ms: endedAt,
                duration_ms: max(endedAt - startedAtMs, 0),
                rms: nil,
                audio_base64: nil,
                metadata: metadata
            )
        )
        continuation?.resume()
        continuation = nil
    }

    private func requestMicrophoneAccess() async -> Bool {
        await withCheckedContinuation { continuation in
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                continuation.resume(returning: granted)
            }
        }
    }

    private func emit(_ event: StreamEvent) {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        guard let data = try? encoder.encode(event) else { return }
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([0x0A]))
    }

    private func extractPCMData(from buffer: AVAudioPCMBuffer) -> Data {
        guard let channelData = buffer.int16ChannelData else {
            return Data()
        }
        let frameLength = Int(buffer.frameLength)
        let bytesPerFrame = MemoryLayout<Int16>.size * Int(buffer.format.channelCount)
        return Data(bytes: channelData[0], count: frameLength * bytesPerFrame)
    }

    private func computeRms(bytes: Data) -> Float {
        if bytes.isEmpty { return 0.0 }
        let sampleCount = bytes.count / MemoryLayout<Int16>.size
        if sampleCount <= 0 { return 0.0 }
        return bytes.withUnsafeBytes { rawBuffer in
            let samples = rawBuffer.bindMemory(to: Int16.self)
            var sum: Float = 0.0
            for sample in samples {
                let normalized = Float(sample) / Float(Int16.max)
                sum += normalized * normalized
            }
            return sqrt(sum / Float(sampleCount))
        }
    }
}

let args = CommandLine.arguments
let listenTimeout = Double(argumentValue(args: args, name: "--listen-timeout") ?? "8.0") ?? 8.0
let silenceTimeout = Double(argumentValue(args: args, name: "--silence-timeout") ?? "1.2") ?? 1.2
let levelThreshold = Float(argumentValue(args: args, name: "--level-threshold") ?? "0.010") ?? 0.010

let capture = StreamingAudioCapture(
    listenTimeout: listenTimeout,
    silenceTimeout: silenceTimeout,
    levelThreshold: levelThreshold
)

Task {
    await capture.run()
    exit(0)
}

private func argumentValue(args: [String], name: String) -> String? {
    guard let index = args.firstIndex(of: name), index + 1 < args.count else {
        return nil
    }
    return args[index + 1]
}

private func nowMs() -> Int64 {
    Int64(Date().timeIntervalSince1970 * 1000.0)
}

RunLoop.main.run()

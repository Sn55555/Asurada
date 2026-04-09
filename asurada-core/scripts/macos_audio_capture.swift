import AVFoundation
import Foundation

struct CaptureOutput: Codable {
    let status: String
    let audio_file_path: String
    let started_at_ms: Int64
    let ended_at_ms: Int64
    let duration_ms: Int64
    let metadata: [String: String]
}

final class OneShotAudioCapture {
    private let listenTimeout: TimeInterval
    private let silenceTimeout: TimeInterval
    private let levelThreshold: Float
    private let audioEngine = AVAudioEngine()
    private var continuation: CheckedContinuation<CaptureOutput, Never>?
    private var finishTimer: DispatchSourceTimer?
    private var silenceWorkItem: DispatchWorkItem?
    private var hasFinished = false
    private var hasSpeech = false
    private var startedAtMs: Int64 = 0
    private var audioFileURL: URL?
    private var audioFile: AVAudioFile?

    init(listenTimeout: TimeInterval, silenceTimeout: TimeInterval, levelThreshold: Float) {
        self.listenTimeout = listenTimeout
        self.silenceTimeout = silenceTimeout
        self.levelThreshold = levelThreshold
    }

    func run() async -> CaptureOutput {
        let micAllowed = await requestMicrophoneAccess()
        guard micAllowed else {
            return makeOutput(
                status: "microphone_denied",
                audioPath: "",
                metadata: ["microphone_access": "denied"]
            )
        }

        startedAtMs = nowMs()
        return await withCheckedContinuation { continuation in
            self.continuation = continuation
            self.startCapture()
        }
    }

    private func startCapture() {
        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)

        do {
            let outputURL = makeOutputURL()
            audioFileURL = outputURL
            audioFile = try AVAudioFile(forWriting: outputURL, settings: format.settings)
        } catch {
            finish(
                status: "audio_file_error",
                metadata: ["error": error.localizedDescription]
            )
            return
        }

        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            guard let self else { return }
            do {
                try self.audioFile?.write(from: buffer)
            } catch {
                self.finish(
                    status: "audio_file_error",
                    metadata: ["error": error.localizedDescription]
                )
                return
            }

            let rms = self.computeRms(buffer: buffer)
            if rms >= self.levelThreshold {
                self.hasSpeech = true
                self.resetSilenceTimer()
            }
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            finish(
                status: "audio_engine_error",
                metadata: ["error": error.localizedDescription]
            )
            return
        }

        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global())
        timer.schedule(deadline: .now() + listenTimeout)
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            if self.hasSpeech {
                self.finish(
                    status: "recorded_timeout",
                    metadata: ["timeout": "listen_timeout"]
                )
            } else {
                self.finish(
                    status: "timeout_no_speech",
                    metadata: ["timeout": "listen_timeout"]
                )
            }
        }
        timer.resume()
        finishTimer = timer
    }

    private func resetSilenceTimer() {
        silenceWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.finish(status: "recorded", metadata: ["timeout": "silence_timeout"])
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
        let output = makeOutput(
            status: status,
            audioPath: audioFileURL?.path ?? "",
            metadata: metadata
        )
        continuation?.resume(returning: output)
        continuation = nil
    }

    private func makeOutput(status: String, audioPath: String, metadata: [String: String]) -> CaptureOutput {
        CaptureOutput(
            status: status,
            audio_file_path: audioPath,
            started_at_ms: startedAtMs == 0 ? nowMs() : startedAtMs,
            ended_at_ms: nowMs(),
            duration_ms: max(nowMs() - (startedAtMs == 0 ? nowMs() : startedAtMs), 0),
            metadata: metadata
        )
    }

    private func requestMicrophoneAccess() async -> Bool {
        await withCheckedContinuation { continuation in
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                continuation.resume(returning: granted)
            }
        }
    }

    private func makeOutputURL() -> URL {
        let filename = "asurada_open_asr_\(UUID().uuidString).caf"
        return URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent(filename)
    }

    private func computeRms(buffer: AVAudioPCMBuffer) -> Float {
        guard let channelData = buffer.floatChannelData else {
            return 0.0
        }
        let channel = channelData[0]
        let frameLength = Int(buffer.frameLength)
        if frameLength <= 0 {
            return 0.0
        }
        var sum: Float = 0.0
        for index in 0..<frameLength {
            let sample = channel[index]
            sum += sample * sample
        }
        return sqrt(sum / Float(frameLength))
    }
}

let args = CommandLine.arguments
let listenTimeout = Double(argumentValue(args: args, name: "--listen-timeout") ?? "6.0") ?? 6.0
let silenceTimeout = Double(argumentValue(args: args, name: "--silence-timeout") ?? "1.0") ?? 1.0
let levelThreshold = Float(argumentValue(args: args, name: "--level-threshold") ?? "0.010") ?? 0.010

let capture = OneShotAudioCapture(
    listenTimeout: listenTimeout,
    silenceTimeout: silenceTimeout,
    levelThreshold: levelThreshold
)

Task {
    let result = await capture.run()
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]
    guard let data = try? encoder.encode(result),
          let text = String(data: data, encoding: .utf8) else {
        fputs("{\"status\":\"encoding_error\",\"audio_file_path\":\"\",\"started_at_ms\":0,\"ended_at_ms\":0,\"duration_ms\":0,\"metadata\":{}}\n", stderr)
        exit(1)
    }
    print(text)
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

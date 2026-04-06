import AVFoundation
import Foundation
import Speech

struct RecognitionOutput: Codable {
    let status: String
    let transcript_text: String
    let confidence: Double?
    let started_at_ms: Int64
    let ended_at_ms: Int64
    let locale: String
    let metadata: [String: String]
}

final class OneShotSpeechCapture {
    private let localeIdentifier: String
    private let listenTimeout: TimeInterval
    private let silenceTimeout: TimeInterval
    private let audioEngine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var continuation: CheckedContinuation<RecognitionOutput, Never>?
    private var finishTimer: DispatchSourceTimer?
    private var silenceWorkItem: DispatchWorkItem?
    private var hasFinished = false
    private var latestTranscript = ""
    private var latestConfidence: Double?
    private var startedAtMs: Int64 = 0

    init(localeIdentifier: String, listenTimeout: TimeInterval, silenceTimeout: TimeInterval) {
        self.localeIdentifier = localeIdentifier
        self.listenTimeout = listenTimeout
        self.silenceTimeout = silenceTimeout
    }

    func run() async -> RecognitionOutput {
        let speechStatus = await requestSpeechAuthorization()
        guard speechStatus == .authorized else {
            return makeOutput(
                status: "authorization_denied",
                transcript: "",
                confidence: nil,
                metadata: ["speech_authorization": authorizationLabel(speechStatus)]
            )
        }

        let micAllowed = await requestMicrophoneAccess()
        guard micAllowed else {
            return makeOutput(
                status: "microphone_denied",
                transcript: "",
                confidence: nil,
                metadata: ["microphone_access": "denied"]
            )
        }

        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: localeIdentifier)), recognizer.isAvailable else {
            return makeOutput(
                status: "recognizer_unavailable",
                transcript: "",
                confidence: nil,
                metadata: ["locale": localeIdentifier]
            )
        }

        startedAtMs = nowMs()
        return await withCheckedContinuation { continuation in
            self.continuation = continuation
            self.startCapture(recognizer: recognizer)
        }
    }

    private func startCapture(recognizer: SFSpeechRecognizer) {
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        self.recognitionRequest = request

        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.recognitionRequest?.append(buffer)
        }

        recognitionTask = recognizer.recognitionTask(with: request) { [weak self] result, error in
            guard let self else { return }
            if let result {
                let transcript = result.bestTranscription.formattedString.trimmingCharacters(in: .whitespacesAndNewlines)
                if !transcript.isEmpty {
                    self.latestTranscript = transcript
                    let confidences = result.bestTranscription.segments.map { Double($0.confidence) }
                    if !confidences.isEmpty {
                        self.latestConfidence = confidences.reduce(0.0, +) / Double(confidences.count)
                    }
                    self.resetSilenceTimer()
                }
                if result.isFinal {
                    self.finish(
                        status: self.latestTranscript.isEmpty ? "no_speech" : "recognized",
                        transcript: self.latestTranscript,
                        confidence: self.latestConfidence,
                        metadata: ["final_result": "true"]
                    )
                    return
                }
            }

            if let error {
                self.finish(
                    status: self.latestTranscript.isEmpty ? "error" : "recognized_partial",
                    transcript: self.latestTranscript,
                    confidence: self.latestConfidence,
                    metadata: ["error": error.localizedDescription]
                )
            }
        }

        do {
            audioEngine.prepare()
            try audioEngine.start()
        } catch {
            finish(
                status: "audio_engine_error",
                transcript: "",
                confidence: nil,
                metadata: ["error": error.localizedDescription]
            )
            return
        }

        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.global())
        timer.schedule(deadline: .now() + listenTimeout)
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            let status = self.latestTranscript.isEmpty ? "timeout_no_speech" : "recognized_partial"
            self.finish(
                status: status,
                transcript: self.latestTranscript,
                confidence: self.latestConfidence,
                metadata: ["timeout": "listen_timeout"]
            )
        }
        timer.resume()
        finishTimer = timer
    }

    private func resetSilenceTimer() {
        silenceWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            guard let self else { return }
            let status = self.latestTranscript.isEmpty ? "timeout_no_speech" : "recognized_partial"
            self.finish(
                status: status,
                transcript: self.latestTranscript,
                confidence: self.latestConfidence,
                metadata: ["timeout": "silence_timeout"]
            )
        }
        silenceWorkItem = workItem
        DispatchQueue.global().asyncAfter(deadline: .now() + silenceTimeout, execute: workItem)
    }

    private func finish(status: String, transcript: String, confidence: Double?, metadata: [String: String]) {
        guard !hasFinished else { return }
        hasFinished = true
        silenceWorkItem?.cancel()
        finishTimer?.cancel()
        finishTimer = nil
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        let output = makeOutput(
            status: status,
            transcript: transcript,
            confidence: confidence,
            metadata: metadata
        )
        continuation?.resume(returning: output)
        continuation = nil
    }

    private func makeOutput(status: String, transcript: String, confidence: Double?, metadata: [String: String]) -> RecognitionOutput {
        RecognitionOutput(
            status: status,
            transcript_text: transcript,
            confidence: confidence,
            started_at_ms: startedAtMs == 0 ? nowMs() : startedAtMs,
            ended_at_ms: nowMs(),
            locale: localeIdentifier,
            metadata: metadata
        )
    }

    private func requestSpeechAuthorization() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
    }

    private func requestMicrophoneAccess() async -> Bool {
        await withCheckedContinuation { continuation in
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                continuation.resume(returning: granted)
            }
        }
    }

    private func authorizationLabel(_ status: SFSpeechRecognizerAuthorizationStatus) -> String {
        switch status {
        case .authorized:
            return "authorized"
        case .denied:
            return "denied"
        case .restricted:
            return "restricted"
        case .notDetermined:
            return "not_determined"
        @unknown default:
            return "unknown"
        }
    }
}

let args = CommandLine.arguments
let locale = argumentValue(args: args, name: "--locale") ?? "zh-CN"
let listenTimeout = Double(argumentValue(args: args, name: "--listen-timeout") ?? "6.0") ?? 6.0
let silenceTimeout = Double(argumentValue(args: args, name: "--silence-timeout") ?? "1.0") ?? 1.0
let capture = OneShotSpeechCapture(
    localeIdentifier: locale,
    listenTimeout: listenTimeout,
    silenceTimeout: silenceTimeout
)

Task {
    let result = await capture.run()
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.withoutEscapingSlashes]
    guard let data = try? encoder.encode(result),
          let text = String(data: data, encoding: .utf8) else {
        fputs("{\"status\":\"encoding_error\",\"transcript_text\":\"\",\"confidence\":null,\"started_at_ms\":0,\"ended_at_ms\":0,\"locale\":\"\(locale)\",\"metadata\":{}}\n", stderr)
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

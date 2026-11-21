import AppKit
import Foundation

final class VoiceApp: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    let transcript = NSTextView()
    let status = NSTextField(labelWithString: "正在连接语音服务…")
    var process: Process?
    var input: Pipe?
    var output: Pipe?
    var logText = ""
    var logURL: URL?
    var closing = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 760, height: 470), styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = "Asurada Voice"
        window.center()
        let stack = NSStackView()
        stack.orientation = .vertical; stack.alignment = .leading; stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        let notice = NSTextField(wrappingLabelWithString: "点击开始聆听后，说“阿斯拉达，当前燃油够跑吗？”\n麦克风音频由 Apple 系统语音识别处理，可能使用在线服务。")
        stack.addArrangedSubview(notice)
        stack.addArrangedSubview(status)
        let buttons = NSStackView()
        for (title, action) in [("开始聆听", #selector(listen)), ("停止播报", #selector(stop)), ("重连语音服务", #selector(reconnect))] {
            buttons.addArrangedSubview(NSButton(title: title, target: self, action: action))
        }
        stack.addArrangedSubview(buttons)
        let scroll = NSScrollView(); scroll.hasVerticalScroller = true
        transcript.isEditable = false; transcript.isRichText = false
        transcript.font = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
        scroll.documentView = transcript
        transcript.autoresizingMask = [.width]
        transcript.textContainer?.widthTracksTextView = true
        stack.addArrangedSubview(scroll)
        let content = window.contentView!
        content.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 18), stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -18), stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 18), stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -18), scroll.widthAnchor.constraint(equalTo: stack.widthAnchor), scroll.heightAnchor.constraint(greaterThanOrEqualToConstant: 250)])
        let menu = NSMenu(); let item = NSMenuItem(); menu.addItem(item)
        let appMenu = NSMenu(); appMenu.addItem(withTitle: "退出 Asurada Voice", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q"); item.submenu = appMenu; NSApp.mainMenu = menu
        window.makeKeyAndOrderFront(nil); NSApp.activate(ignoringOtherApps: true)
        launchLoop()
    }

    func append(_ text: String) {
        logText += text
        if logText.utf8.count > 200_000 { logText = String(logText.suffix(80_000)) }
        transcript.string = logText; transcript.scrollToEndOfDocument(nil)
        if let url = logURL { try? logText.write(to: url, atomically: true, encoding: .utf8) }
        if text.contains("listening...") { status.stringValue = "正在聆听，请说测试语句…" }
        if text.contains("mode=manual") || text.contains("recognizer status=") { status.stringValue = "已连接，点击开始聆听" }
        if text.contains("recognizer_error=") { status.stringValue = "识别未完成，请查看下方错误" }
    }

    func launchLoop() {
        guard process == nil else { return }
        guard let root = Bundle.main.object(forInfoDictionaryKey: "AsuradaRepositoryRoot") as? String else { append("缺少项目路径\n"); return }
        let args = CommandLine.arguments
        let index = args.firstIndex(of: "--runtime-dir")
        let runtime = index.flatMap { $0 + 1 < args.count ? args[$0 + 1] : nil } ?? root + "/asurada-core/runtime_logs"
        logURL = URL(fileURLWithPath: runtime).appendingPathComponent("voice-app.log")
        let child = Process(); child.executableURL = URL(fileURLWithPath: root + "/asurada-core/.venv/bin/python")
        child.currentDirectoryURL = URL(fileURLWithPath: root)
        child.arguments = ["-u", root + "/asurada-core/scripts/phase3_macos_voice_loop.py", "--session-log", runtime + "/session_log.jsonl", "--recognizer-backend", "macos_speech", "--manual"]
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = root + "/asurada-core/src"
        env["ASURADA_RUNTIME_DIR"] = runtime
        env["ASURADA_MACOS_COMMAND_TIMEOUT_S"] = "90"
        env["ASURADA_MACOS_LISTEN_TIMEOUT_S"] = "12"
        child.environment = env
        let stdinPipe = Pipe(); let stdoutPipe = Pipe()
        child.standardInput = stdinPipe; child.standardOutput = stdoutPipe; child.standardError = stdoutPipe
        input = stdinPipe; output = stdoutPipe
        stdoutPipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            guard !data.isEmpty else { handle.readabilityHandler = nil; return }
            let text = String(decoding: data, as: UTF8.self)
            DispatchQueue.main.async { self?.append(text) }
        }
        child.terminationHandler = { [weak self] child in
            DispatchQueue.main.async {
                self?.append("\n语音循环已退出：\(child.terminationStatus)\n")
                self?.process = nil; self?.input = nil
                self?.status.stringValue = "语音循环已停止，可重连"
                if self?.closing == true { NSApp.reply(toApplicationShouldTerminate: true) }
            }
        }
        do { try child.run(); process = child } catch { append("启动失败：\(error.localizedDescription)\n") }
    }
    func send(_ text: String) {
        guard process?.isRunning == true, let handle = input?.fileHandleForWriting else { append("请先重连语音服务\n"); return }
        do { try handle.write(contentsOf: Data(text.utf8)) } catch { append("命令发送失败：\(error.localizedDescription)\n") }
    }
    @objc func listen() { send("\n") }
    @objc func stop() { send("s\n") }
    @objc func reconnect() { launchLoop() }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let child = process, child.isRunning else { return .terminateNow }
        closing = true; send("q\n")
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { if child.isRunning { child.interrupt() } }
        return .terminateLater
    }
}
let app = NSApplication.shared
let delegate = VoiceApp()
app.delegate = delegate
app.run()

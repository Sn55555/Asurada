# Asurada Voice（本机验收入口）

独立 AppKit 应用承载现有 Python 手动语音循环，通过 LaunchServices 启动，使 macOS 将麦克风和 Speech 权限归属到 `com.asurada.voice`。应用声明 `NSMicrophoneUsageDescription` 和 `NSSpeechRecognitionUsageDescription`；不修改 Codex.app，不改动 TCC 数据库。

在项目根目录运行：

```sh
./script/build_and_run.sh --verify /Users/sn5/Asurada/output/user-acceptance/current/runtime
```

默认运行目录为 `asurada-core/runtime_logs`，也可用第二个参数指定。核心遥测及共享语音服务须先启动。`--build-only` 只构建。产物位于 `output/macos-voice/Asurada Voice.app`，为本机构建并临时签名，未做发行公证。

- 开始聆听：手动触发一轮 Apple 语音识别，需系统权限；音频可能由 Apple 在线服务处理。
- 停止播报：使用现有语音循环的停止入口。
- 重连语音服务：语音循环退出后重新连接，不创建第二个播放器。
- 关闭窗口：请求语音循环退出；未及时退出时发送中断。

界面及 `voice-app.log` 仅保留有限长度的运行文字记录，不保存原始音频。日志位于所选 runtime 目录。麦克风不会在启动应用时自动采集。

## 本轮验证

2026-09-15：构建、临时签名校验、Info.plist 校验和启动成功。实际通过 Apple Speech 返回 `recognized_partial` 转写，原先缺少用途声明导致的 TCC 崩溃不再出现。首轮转写把“阿斯拉达”识别为“阿斯拉德”，被现有唤醒词规则拒绝；权限入口修复通过不等于唤醒问答已经通过。

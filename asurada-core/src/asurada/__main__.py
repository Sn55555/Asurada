from __future__ import annotations

import argparse
from pathlib import Path

from .app import AsuradaApp
from .config import AppConfig, UdpConfig


def build_parser() -> argparse.ArgumentParser:
    # 备注:
    # CLI 入口统一收敛到这里，后续新增模式先加参数，
    # 再在 main() 里分发到 AsuradaApp 对应运行路径。
    parser = argparse.ArgumentParser(description="Asurada racing strategy brain")
    parser.add_argument(
        "--replay",
        type=Path,
        default=Path("data/sample_session.jsonl"),
        help="Path to normalized JSONL replay snapshots.",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the bundled sample replay.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        help="Run a single-lap CSV exported by the recorder tool.",
    )
    parser.add_argument(
        "--capture-jsonl",
        type=Path,
        help="Replay a raw UDP capture JSONL file and decode F1 25 packet headers.",
    )
    parser.add_argument(
        "--live-udp",
        action="store_true",
        help="Start the live UDP real-time runtime path for F1 25 packets.",
    )
    parser.add_argument(
        "--build-dashboard",
        action="store_true",
        help="Build a local HTML debug dashboard from runtime_logs/session_log.jsonl.",
    )
    parser.add_argument(
        "--session-paced",
        action="store_true",
        help="Replay capture snapshots paced by in-game session_time_s.",
    )
    parser.add_argument(
        "--pace-multiplier",
        type=float,
        default=1.0,
        help="Speed multiplier for session-paced capture replay.",
    )
    parser.add_argument(
        "--udp-host",
        default="0.0.0.0",
        help="Host to bind the UDP listener.",
    )
    parser.add_argument(
        "--udp-port",
        type=int,
        default=20778,
        help="Port to bind the UDP listener.",
    )
    return parser


def main() -> None:
    # 备注:
    # 当前优先级按“显式模式参数优先，默认 replay 兜底”执行。
    # 这样 demo、csv、capture、live-udp、dashboard 不会互相冲突。
    parser = build_parser()
    args = parser.parse_args()
    app = AsuradaApp(AppConfig())
    if args.csv is not None:
        app.run_csv_lap(args.csv)
        return
    if args.capture_jsonl is not None:
        app.run_capture_replay(
            args.capture_jsonl,
            session_paced=args.session_paced,
            pace_multiplier=args.pace_multiplier,
        )
        return
    if args.live_udp:
        app.run_live_udp(UdpConfig(host=args.udp_host, port=args.udp_port))
        return
    if args.build_dashboard:
        app.build_debug_dashboard()
        return

    replay_path = Path("data/sample_session.jsonl") if args.demo else args.replay
    app.run_replay(replay_path)


if __name__ == "__main__":
    main()

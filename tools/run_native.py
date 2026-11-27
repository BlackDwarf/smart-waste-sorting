"""本机原生窗口启动器。

双击项目根目录的“run_local.bat”即可：
1. 自动在后台拉起模拟下位机（已有的端口会复用）；
2. 以**原生窗口**（不是网页）打开分拣控制台；
3. 关闭窗口后自动结束模拟下位机。

    python -m tools.run_native
    python -m tools.run_native --source camera      # 直接开摄像头
    python -m tools.run_native --no-sim             # 不启动模拟下位机
"""

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="本机原生运行智能垃圾分拣控制台")
    parser.add_argument("--sim-host", default="127.0.0.1")
    parser.add_argument("--sim-port", type=int, default=9000)
    parser.add_argument("--no-sim", action="store_true", help="不自动启动模拟下位机")
    parser.add_argument("--source", default="video", choices=("video", "camera"))
    parser.add_argument("--source-value", default="assets/assessment_demo.mp4")
    parser.add_argument("--weights", default="Predict/best.pt")
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--auto-start", action="store_true", help="界面打开后自动开始识别")
    args = parser.parse_args(argv)

    simulator = None
    if not args.no_sim and not _port_open(args.sim_host, args.sim_port):
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        simulator = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "simulator.lower_simulator",
                "--host",
                args.sim_host,
                "--port",
                str(args.sim_port),
            ],
            cwd=str(ROOT),
            creationflags=creation_flags,
        )
        for _ in range(50):
            if _port_open(args.sim_host, args.sim_port):
                break
            time.sleep(0.1)
        print("模拟下位机已启动：{}:{}".format(args.sim_host, args.sim_port))
    elif not args.no_sim:
        print("检测到 {}:{} 已在运行，直接复用".format(args.sim_host, args.sim_port))

    command = [
        sys.executable,
        "-m",
        "app.main",
        "--sim-host",
        args.sim_host,
        "--sim-port",
        str(args.sim_port),
        "--source",
        args.source,
        "--source-value",
        args.source_value,
        "--weights",
        args.weights,
        "--confidence",
        str(args.confidence),
    ]
    if args.auto_start:
        command.append("--auto-start")

    try:
        return subprocess.call(command, cwd=str(ROOT))
    finally:
        if simulator is not None:
            simulator.terminate()
            try:
                simulator.wait(timeout=5)
            except subprocess.TimeoutExpired:
                simulator.kill()
            print("模拟下位机已停止")


if __name__ == "__main__":
    sys.exit(main())

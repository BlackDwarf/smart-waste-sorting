"""端到端自检：真实 best.pt + 真实 TCP 模拟下位机 + 真实视频帧。

它不启动 Qt 界面，直接复用 :class:`SortingController` 与 :class:`YoloDetector`，
用来验证“视频帧 → YOLO → 状态机 → TCP → 下位机确认 → 计数”这条链路：

    python -m tools.e2e_check --frames 240

退出码 0 表示：至少完成一次完整动作、计数与模拟下位机一致、日志中出现
``WASTE_RESULT → ACK → ACTION_DONE``。
"""

import argparse
import socket
import sys
import threading
import time

from app.controller import SortingController, SystemState
from app.detectors import YoloDetector
from app.protocol import WASTE_NAMES
from app.transport import TcpTransport
from simulator.lower_simulator import LowerComputerSimulator
from vedio.video_module import VideoFileSource


def _free_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="真实权重 + 模拟下位机端到端自检")
    parser.add_argument("--video", default="assets/assessment_demo.mp4")
    parser.add_argument("--weights", default="Predict/best.pt")
    parser.add_argument("--frames", type=int, default=240)
    parser.add_argument("--confidence", type=float, default=0.5)
    parser.add_argument("--action-delay", type=float, default=0.02)
    args = parser.parse_args(argv)

    port = _free_port()
    simulator = LowerComputerSimulator("127.0.0.1", port, action_delay=args.action_delay)
    threading.Thread(target=simulator.serve_forever, daemon=True).start()
    time.sleep(0.3)

    events = []
    logs = []

    def on_event(name, data):
        events.append((name, data))
        if name == "log":
            logs.append(data["message"])
        elif name == "state":
            logs.append("状态 → {}".format(data["value"]))
        elif name in ("tx", "rx"):
            logs.append("{}  {}".format(name.upper(), data["packet"]))

    transport = TcpTransport("127.0.0.1", port)
    controller = SortingController(transport, on_event)
    detector = YoloDetector(args.weights, confidence=args.confidence)
    source = VideoFileSource(args.video)

    per_class = {name: 0 for name in WASTE_NAMES.values()}
    frames_with_detection = 0
    started = time.time()
    processed = 0

    try:
        transport.connect()
        while processed < args.frames:
            ok, frame = source.read()
            if not ok:
                break
            detections = detector.detect(frame)
            best = detections[0] if detections else None
            if best is not None:
                frames_with_detection += 1
                per_class[WASTE_NAMES[best.waste_type]] += 1
            controller.poll()
            controller.process_detection(best)
            processed += 1
        # 把最后一条指令的 ACK / ACTION_DONE 收完
        for _ in range(50):
            controller.poll()
            time.sleep(0.02)
    finally:
        elapsed = time.time() - started
        source.release()
        transport.close()

    total_confirmed = sum(controller.counts.values())
    print("=" * 66)
    print("处理帧数        : {}（{} 帧含目标）".format(processed, frames_with_detection))
    print("耗时            : {:.1f}s（{:.1f} fps）".format(elapsed, processed / max(elapsed, 1e-6)))
    print("模型            : {} ({})".format(args.weights, detector.device))
    print("识别到的类别分布 : ", end="")
    print("，".join("{} {}".format(k, v) for k, v in per_class.items() if v))
    print("上位机计数      : ", end="")
    print("，".join("{} {}".format(name, controller.counts[t]) for t, name in WASTE_NAMES.items()))
    print("模拟下位机完成   : {}".format(simulator.sort_count))
    print("最终状态        : {}".format(controller.state.value))
    print("-" * 66)
    print("关键日志：")
    for line in logs:
        if any(key in line for key in ("WASTE_RESULT", "ACK", "ACTION_DONE", "重发", "满载", "压缩")):
            print("  " + line)
    print("=" * 66)

    problems = []
    if total_confirmed == 0:
        problems.append("没有任何一次完整动作（WASTE_RESULT/ACK/ACTION_DONE）")
    if total_confirmed != simulator.sort_count:
        problems.append(
            "上位机计数 {} 与下位机完成数 {} 不一致".format(total_confirmed, simulator.sort_count)
        )
    if not any(evt[0] == "tx" and evt[1].get("packet", "").startswith("AA 55 03 01") for evt in events):
        problems.append("没有发送过 WASTE_RESULT 帧")
    if controller.state is SystemState.ERROR:
        problems.append("状态机停在通信异常")

    if problems:
        print("自检失败：")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("自检通过：闭环时序与计数一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())

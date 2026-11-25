"""与 UI 无关的分拣状态机。

一次完整动作的时序（对应 TASKS.md 第 4 部分）：

    连续 3 帧同类目标
        → WASTE_RESULT(SEQ, TYPE)          状态 WAIT_ACK
        → ACK(WASTE_RESULT, SEQ)           状态 EXECUTING
        → ACTION_DONE(SEQ)                 计数 +1，状态 COOLDOWN
        → 目标离开画面若干帧                状态 IDLE，允许下一个目标

设计要点：

* **稳定帧**：只有连续 ``stable_frames`` 帧识别为同一类才产生动作，
  避免单帧误检造成的错分。
* **重发**：等待 ACK/ACTION_DONE 超时后用 *原序号* 重发，次数受
  ``max_retries`` 限制，超过后进入 ``ERROR``。
* **计数**：只有收到匹配序号的 ``ACTION_DONE`` 才 +1，ACK 本身不计数。
* **防重复**：同一目标未离开画面（COOLDOWN 期间同类目标仍在）时绝不重发，
  这是“同一个物体不重复计数”的关键。
"""

import time
from enum import Enum
from typing import Callable, Dict, Optional

from .detectors import Detection
from .protocol import Command, Packet, WasteType, WASTE_NAMES
from .transport import Transport, TransportError


class SystemState(Enum):
    IDLE = "等待识别"
    WAIT_ACK = "等待下位机确认"
    EXECUTING = "下位机执行中"
    COOLDOWN = "等待物体离开"
    COMPRESSING = "压缩中"
    PAUSED = "已暂停"
    ERROR = "通信异常"


EventCallback = Callable[[str, dict], None]

# 这些状态下上位机在等回复，不受新的识别结果影响。
_AWAITING_STATES = (SystemState.WAIT_ACK, SystemState.EXECUTING, SystemState.COMPRESSING)


class SortingController:
    def __init__(
        self,
        transport: Transport,
        event_callback: Optional[EventCallback] = None,
        stable_frames: int = 3,
        ack_timeout: float = 2.0,
        max_retries: int = 2,
        compress_after: int = 20,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transport = transport
        self.event_callback = event_callback or (lambda _name, _data: None)
        self.stable_frames = max(1, int(stable_frames))
        self.ack_timeout = float(ack_timeout)
        self.max_retries = max(0, int(max_retries))
        self.compress_after = int(compress_after)
        self.clock = clock
        self.counts = {item: 0 for item in WasteType}
        self.bin_full = {item: False for item in WasteType}
        self.state = SystemState.IDLE
        self.pending = None  # type: Optional[WasteType]
        self._candidate = None  # type: Optional[WasteType]
        self._stable_count = 0
        self._missing_frames = 0
        self._last_packet = None  # type: Optional[Packet]
        self._deadline = 0.0
        self._retry_count = 0
        self._compress_sent = False
        self._sequence = 0
        self._active_sequence = None  # type: Optional[int]
        self._active_waste = None  # type: Optional[WasteType]
        self._cooldown_candidate = None  # type: Optional[WasteType]
        self._cooldown_count = 0
        self._pending_command = None  # type: Optional[Command]
        self._pending_class_name = ""
        self._pending_confidence = 0.0

    # ------------------------------------------------------------- 基础工具
    def _emit(self, name: str, **data) -> None:
        self.event_callback(name, data)

    def _set_state(self, state: SystemState) -> None:
        if state != self.state:
            self.state = state
            self._emit("state", value=state.value)

    @property
    def busy(self) -> bool:
        """是否正在等待下位机回复。"""
        return self.state in _AWAITING_STATES

    def reset(self) -> None:
        self.counts = {item: 0 for item in WasteType}
        self.bin_full = {item: False for item in WasteType}
        self.pending = None
        self._candidate = None
        self._stable_count = 0
        self._missing_frames = 0
        self._last_packet = None
        self._deadline = 0.0
        self._retry_count = 0
        self._compress_sent = False
        self._active_sequence = None
        self._active_waste = None
        self._cooldown_candidate = None
        self._cooldown_count = 0
        self._pending_command = None
        self._pending_class_name = ""
        self._pending_confidence = 0.0
        self._set_state(SystemState.IDLE)
        self._emit("counts", values=self.named_counts())
        self._emit("bins", values=self.named_bins())

    def resume(self) -> None:
        """断线重连 / 切换输入源后清理跟踪状态，但保留已确认的计数。"""
        self._candidate = None
        self._stable_count = 0
        self._missing_frames = 0
        self._cooldown_candidate = None
        self._cooldown_count = 0
        self._active_waste = None
        self._last_packet = None
        self._deadline = 0.0
        self._retry_count = 0
        self._active_sequence = None
        self.pending = None
        self._pending_command = None
        self._pending_class_name = ""
        self._pending_confidence = 0.0
        if self.state in (SystemState.ERROR, SystemState.COOLDOWN, SystemState.EXECUTING,
                          SystemState.WAIT_ACK, SystemState.COMPRESSING):
            self._set_state(SystemState.IDLE)

    def named_counts(self) -> Dict[str, int]:
        return {WASTE_NAMES[key]: value for key, value in self.counts.items()}

    def named_bins(self) -> Dict[str, bool]:
        return {WASTE_NAMES[key]: value for key, value in self.bin_full.items()}

    # ------------------------------------------------------------- 识别入口
    def process_detection(self, detection: Optional[Detection]) -> None:
        """稳定帧判定 + 冷却消抖 + 触发分类指令。

        ``detection`` 为 ``None`` 表示本帧没有目标。
        """
        if self.state is SystemState.ERROR:
            return
        if self.busy:
            # 还有指令没走完 ACK/ACTION_DONE，绝不叠加新指令。
            return

        waste = detection.waste_type if detection is not None else None

        if waste is None:
            # 进入 IDLE 要求的“连续”是严格的：中间出现空帧就重新计数。
            self._candidate = None
            self._stable_count = 0
            self._cooldown_candidate = None
            self._cooldown_count = 0
            self._missing_frames += 1
            if self._missing_frames >= self.stable_frames and self.state is SystemState.COOLDOWN:
                # COOLDOWN 里允许短暂丢帧，连续若干帧都没有目标才认为物体已离开。
                self._active_waste = None
                self._set_state(SystemState.IDLE)
            return

        self._missing_frames = 0

        if self.state is SystemState.COOLDOWN:
            if waste == self._active_waste:
                # 同一物体仍在画面中：不重复发送、不重复计数。
                self._cooldown_candidate = None
                self._cooldown_count = 0
                return
            if waste == self._cooldown_candidate:
                self._cooldown_count += 1
            else:
                self._cooldown_candidate = waste
                self._cooldown_count = 1
            if self._cooldown_count >= self.stable_frames:
                self._cooldown_candidate = None
                self._cooldown_count = 0
                self._send_classification(
                    waste, detection.class_name, detection.confidence
                )
            return

        # IDLE：累计连续稳定帧。
        if waste == self._candidate:
            self._stable_count += 1
        else:
            self._candidate = waste
            self._stable_count = 1
        if self._stable_count >= self.stable_frames:
            self._stable_count = 0
            self._candidate = None
            self._send_classification(waste, detection.class_name, detection.confidence)

    # ------------------------------------------------------------- 发送
    def _send_packet(self, packet: Packet, wait_for_reply: bool = True) -> bool:
        try:
            self.transport.send(packet)
        except TransportError as exc:
            self._set_state(SystemState.ERROR)
            self._emit("log", message="发送失败：{}".format(exc))
            return False
        self._emit("tx", packet=packet.encode().hex(" ").upper())
        if wait_for_reply:
            self._last_packet = packet
            self._deadline = self.clock() + self.ack_timeout
            self._retry_count = 0
        return True

    def _next_sequence(self) -> int:
        """八位序号循环递增（1~255，0 也合法但跳过，便于日志辨识）。"""
        self._sequence = (self._sequence % 255) + 1
        return self._sequence

    def _send_classification(
        self,
        waste_type: WasteType,
        class_name: str = "",
        confidence: float = 0.0,
    ) -> None:
        """处理满载、序号，并发送 WASTE_RESULT。

        ``class_name`` 是模型输出的**原始类别**（如 papercup），日志里会一并打印，
        方便对着视频核对“模型看到的到底是什么”。
        """
        self._active_waste = waste_type
        self._pending_class_name = class_name or WASTE_NAMES[waste_type]
        self._pending_confidence = float(confidence or 0.0)
        detail = self._pending_class_name
        if confidence:
            detail = "{}（置信度 {:.0f}%）".format(detail, confidence * 100)

        if self.bin_full.get(waste_type):
            self._emit(
                "log",
                message="识别稳定：{} → {}，但桶已满，跳过本次分类（等待清运后继续）".format(
                    detail, WASTE_NAMES[waste_type]
                ),
            )
            self._set_state(SystemState.COOLDOWN)
            return

        sequence = self._next_sequence()
        packet = Packet(Command.WASTE_RESULT, bytes((sequence, int(waste_type))))
        self.pending = waste_type
        self._active_sequence = sequence
        self._pending_command = Command.WASTE_RESULT
        if not self._send_packet(packet):
            self.pending = None
            self._active_sequence = None
            self._pending_command = None
            self._active_waste = None
            return
        self._set_state(SystemState.WAIT_ACK)
        self._emit(
            "log",
            message="识别稳定：{} → {}（序号 {}）→ 已发送 WASTE_RESULT".format(
                detail, WASTE_NAMES[waste_type], sequence
            ),
        )

    # ------------------------------------------------------------- 轮询
    def poll(self) -> None:
        """轮询接收；等待超时后重发，超过次数进入 ERROR。"""
        for packet in self.transport.poll():
            self._emit("rx", packet=packet.encode().hex(" ").upper())
            self.handle_packet(packet)
        self._check_timeout()

    def _check_timeout(self) -> None:
        if self.state not in _AWAITING_STATES or self._last_packet is None:
            return
        now = self.clock()
        if now < self._deadline:
            return

        if self._retry_count < self.max_retries:
            self._retry_count += 1
            packet = self._last_packet
            try:
                self.transport.send(packet)
            except TransportError as exc:
                self._set_state(SystemState.ERROR)
                self._emit("log", message="重发失败：{}".format(exc))
                self._last_packet = None
                return
            self._emit("tx", packet=packet.encode().hex(" ").upper())
            self._deadline = now + self.ack_timeout
            self._emit(
                "log",
                message="等待下位机超时，第 {} 次用原序号 {} 重发".format(
                    self._retry_count, self._active_sequence
                ),
            )
            return

        self._emit(
            "log",
            message="等待下位机超时且重发 {} 次仍无响应，进入通信异常".format(self.max_retries),
        )
        self._last_packet = None
        self._deadline = 0.0
        self._set_state(SystemState.ERROR)

    # ------------------------------------------------------------- 收包
    def handle_packet(self, packet: Packet) -> None:
        """处理 ACK、ACTION_DONE、BIN_FULL 和 ERROR。"""
        command = packet.command

        if command == Command.ACK:
            self._handle_ack(packet)
        elif command == Command.ACTION_DONE:
            self._handle_action_done(packet)
        elif command == Command.BIN_FULL:
            self._handle_bin_full(packet)
        elif command == Command.ERROR:
            message = packet.payload.decode("utf-8", "replace")
            self._emit("log", message="下位机报错：{}".format(message or "（无文本）"))
            self._last_packet = None
            self._deadline = 0.0
            self._set_state(SystemState.ERROR)

    def _handle_ack(self, packet: Packet) -> None:
        payload = packet.payload
        if len(payload) < 2:
            self._emit("log", message="ACK 载荷不完整：{}".format(payload.hex(" ").upper()))
            return
        original_command, sequence = payload[0], payload[1]
        if self._pending_command is None or original_command != int(self._pending_command):
            self._emit(
                "log",
                message="忽略无关 ACK（原命令 0x{:02X}）".format(original_command),
            )
            return
        if self._active_sequence is not None and sequence != self._active_sequence:
            self._emit(
                "log",
                message="忽略过期 ACK（序号 {}，当前 {}）".format(sequence, self._active_sequence),
            )
            return
        if self.state in (SystemState.WAIT_ACK, SystemState.COMPRESSING):
            self._deadline = self.clock() + self.ack_timeout
            self._set_state(SystemState.EXECUTING)
            self._emit("log", message="收到 ACK（序号 {}），等待 ACTION_DONE".format(sequence))

    def _handle_action_done(self, packet: Packet) -> None:
        if not packet.payload:
            self._emit("log", message="ACTION_DONE 缺少序号")
            return
        sequence = packet.payload[0]
        if self._active_sequence is None or sequence != self._active_sequence:
            self._emit("log", message="忽略过期 ACTION_DONE（序号 {}）".format(sequence))
            return
        if self.state not in _AWAITING_STATES:
            return

        is_compress = self._pending_command is Command.START_COMPRESS
        self._last_packet = None
        self._deadline = 0.0
        self._retry_count = 0
        self._active_sequence = None
        self._pending_command = None

        if is_compress:
            self._emit("log", message="压缩动作完成（序号 {}）".format(sequence))
            self._set_state(SystemState.COOLDOWN)
            return

        waste_type = self.pending
        self.pending = None
        if waste_type is None:
            return
        self.counts[waste_type] += 1
        total = sum(self.counts.values())
        self._emit("counts", values=self.named_counts())
        self._emit(
            "log",
            message="WASTE_RESULT → ACK → ACTION_DONE 完成：{} / {}，本类累计 {}，总计 {}".format(
                self._pending_class_name or "—",
                WASTE_NAMES[waste_type],
                self.counts[waste_type],
                total,
            ),
        )
        self._pending_class_name = ""
        self._pending_confidence = 0.0
        self._set_state(SystemState.COOLDOWN)
        self._maybe_compress()

    def _handle_bin_full(self, packet: Packet) -> None:
        if not packet.payload:
            self._emit("log", message="BIN_FULL 缺少垃圾类型")
            return
        try:
            waste_type = WasteType(packet.payload[0])
        except ValueError:
            self._emit(
                "log",
                message="BIN_FULL 类型未知：0x{:02X}".format(packet.payload[0]),
            )
            return
        if not self.bin_full[waste_type]:
            self.bin_full[waste_type] = True
            self._emit("bins", values=self.named_bins())
            self._emit("log", message="下位机上报：{}桶已满".format(WASTE_NAMES[waste_type]))

    # ------------------------------------------------------------- 加分项
    def _maybe_compress(self) -> None:
        """累计分拣数量达到阈值后发送一次 START_COMPRESS。"""
        if self._compress_sent or self.compress_after <= 0:
            return
        total = sum(self.counts.values())
        if total < self.compress_after:
            return
        self._compress_sent = True
        sequence = self._next_sequence()
        packet = Packet(Command.START_COMPRESS, bytes((sequence,)))
        self.pending = None
        self._active_sequence = sequence
        self._pending_command = Command.START_COMPRESS
        if not self._send_packet(packet):
            self._active_sequence = None
            self._pending_command = None
            return
        self._set_state(SystemState.COMPRESSING)
        self._emit(
            "log",
            message="累计分拣 {} 件，达到压缩阈值，发送 START_COMPRESS（序号 {}）".format(
                total, sequence
            ),
        )



"""上位机通信协议。

帧格式请阅读仓库根目录的 ``PROTOCOL.md``：

    +------+--------+---------+-----------+----------+
    | HEAD | LENGTH | COMMAND |  PAYLOAD  | CHECKSUM |
    | AA55 |   1B   |   1B    |  N bytes  |    1B    |
    +------+--------+---------+-----------+----------+

``LENGTH`` = ``COMMAND + PAYLOAD`` 的字节数（1~64），``CHECKSUM`` 为从
``LENGTH`` 到 ``PAYLOAD`` 末字节的累加和低 8 位。

TCP 和串口都是字节流，一次 ``recv`` 可能得到半帧、多帧或带噪声的数据，
所以接收端必须使用 :class:`StreamParser` 增量解析，不能假设“一次读到一帧”。
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import List, Optional


HEADER = b"\xAA\x55"
MAX_BODY_LENGTH = 64
MAX_PAYLOAD_LENGTH = MAX_BODY_LENGTH - 1  # COMMAND 占 1 字节
MIN_BODY_LENGTH = 1


class Command(IntEnum):
    WASTE_RESULT = 0x01
    ACK = 0x02
    ACTION_DONE = 0x03
    BIN_FULL = 0x04
    START_COMPRESS = 0x05
    HEARTBEAT = 0x06
    ERROR = 0x7F


class WasteType(IntEnum):
    HAZARDOUS = 0x01
    OTHER = 0x02
    RECYCLABLE = 0x03
    KITCHEN = 0x04


WASTE_NAMES = {
    WasteType.RECYCLABLE: "可回收垃圾",
    WasteType.KITCHEN: "厨余垃圾",
    WasteType.HAZARDOUS: "有害垃圾",
    WasteType.OTHER: "其他垃圾",
}


@dataclass(frozen=True)
class Packet:
    command: Command
    payload: bytes = b""

    def encode(self) -> bytes:
        """按协议生成完整二进制帧。

        校验：
        * ``payload`` 必须是 bytes 类对象；
        * ``COMMAND + PAYLOAD`` 长度必须落在 1~64 字节内；
        * ``CHECKSUM = (LENGTH + sum(COMMAND + PAYLOAD)) & 0xFF``。
        """
        if not isinstance(self.payload, (bytes, bytearray, memoryview)):
            raise TypeError("payload 必须是 bytes，当前为 {}".format(type(self.payload).__name__))
        payload = bytes(self.payload)
        if len(payload) > MAX_PAYLOAD_LENGTH:
            raise ValueError(
                "载荷过长：{} 字节，最多 {} 字节".format(len(payload), MAX_PAYLOAD_LENGTH)
            )

        command = int(self.command)
        if not 0 <= command <= 0xFF:
            raise ValueError("命令字必须在 0~255 之间：{}".format(command))

        length = 1 + len(payload)
        body = bytes((command,)) + payload
        checksum = (length + sum(body)) & 0xFF
        return HEADER + bytes((length,)) + body + bytes((checksum,))


class StreamParser:
    """把任意分片的 TCP/串口字节流增量解析为 Packet。

    解析循环遵循“找到帧头 → 校验长度 → 等够整帧 → 校验和”的顺序：

    * 帧头之前的所有字节都是噪声，直接丢弃并计数；
    * 长度非法或校验和错误时只丢弃 **1 个字节** 后重新寻找帧头，
      这样即使坏帧内部恰好包含 ``AA 55`` 也能继续同步；
    * 数据不够一整帧时保留在缓冲区，等待下一次 ``feed``。
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.error_count = 0
        self.discarded_bytes = 0
        self._noise_reported = False

    def reset(self) -> None:
        self._buffer.clear()
        self.error_count = 0
        self.discarded_bytes = 0
        self._noise_reported = False

    @property
    def buffered_bytes(self) -> int:
        """当前尚未凑成完整帧的字节数（调试/UI 用）。"""
        return len(self._buffer)

    def _drop(self, count: int) -> None:
        if count <= 0:
            return
        del self._buffer[:count]
        self.discarded_bytes += count

    def feed(self, data: bytes) -> List[Packet]:
        """支持半包、粘包、噪声和错误校验后的重新同步。"""
        if not data:
            return []
        self._buffer.extend(data)

        packets = []  # type: List[Packet]
        while True:
            # 1. 丢弃帧头之前的噪声，保留可能是半个帧头的最后一个 0xAA。
            start = self._buffer.find(HEADER)
            if start < 0:
                if not self._buffer:
                    break
                keep = 1 if self._buffer[-1] == HEADER[0] else 0
                drop = len(self._buffer) - keep
                if drop > 0:
                    self._count_noise()
                    self._drop(drop)
                break
            if start > 0:
                self._count_noise()
                self._drop(start)

            # 2. 长度字段尚未到达，等待下一次 feed。
            if len(self._buffer) < 3:
                break
            length = self._buffer[2]
            if length < MIN_BODY_LENGTH or length > MAX_BODY_LENGTH:
                # 长度非法：几乎肯定是错位，丢掉帧头首字节后重新同步。
                self._count_error()
                self._drop(1)
                continue

            # 3. 整帧尚未到齐，保留缓冲区等待。
            frame_size = 2 + 1 + length + 1
            if len(self._buffer) < frame_size:
                break

            body = bytes(self._buffer[3 : 3 + length])
            checksum = self._buffer[3 + length]
            if ((length + sum(body)) & 0xFF) != checksum:
                # 校验失败：只丢 1 字节，保留后面的潜在合法帧。
                self._count_error()
                self._drop(1)
                continue

            try:
                command = Command(body[0])
            except ValueError:
                # 校验正确但命令字未定义：整帧丢弃，避免把错误当成正常指令。
                self._count_error()
                self._drop(frame_size)
                continue

            packets.append(Packet(command, body[1:]))
            self._drop(frame_size)
            self._noise_reported = False

        return packets

    def _count_noise(self) -> None:
        """同一段噪声只记一次错误，避免重同步的连带丢弃重复计数。"""
        if not self._noise_reported:
            self.error_count += 1
            self._noise_reported = True

    def _count_error(self) -> None:
        self.error_count += 1
        self._noise_reported = True

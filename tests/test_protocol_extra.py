"""协议层的边界测试（补充公开测试，覆盖隐藏测试常考的点）。"""

import unittest

from app.protocol import (
    HEADER,
    MAX_BODY_LENGTH,
    Command,
    Packet,
    StreamParser,
    WasteType,
)


def _frame(command: int, payload: bytes, length: int = None, checksum: int = None) -> bytes:
    """手工构造一帧，用来制造非法长度/非法校验。"""
    body = bytes((command,)) + payload
    real_length = len(body)
    length = real_length if length is None else length
    real_checksum = (real_length + sum(body)) & 0xFF
    checksum = real_checksum if checksum is None else checksum
    return HEADER + bytes((length,)) + body + bytes((checksum,))


class EncodeTests(unittest.TestCase):
    def test_protocol_document_example_is_byte_exact(self):
        packet = Packet(Command.WASTE_RESULT, b"\x11\x03")
        self.assertEqual(packet.encode(), bytes.fromhex("AA550301110318"))

    def test_every_waste_type_round_trips(self):
        parser = StreamParser()
        packets = [
            Packet(Command.WASTE_RESULT, bytes((index, int(waste))))
            for index, waste in enumerate(WasteType, start=1)
        ]
        data = b"".join(packet.encode() for packet in packets)
        self.assertEqual(parser.feed(data), packets)

    def test_maximum_payload_is_accepted_and_longer_is_rejected(self):
        payload = bytes(range(MAX_BODY_LENGTH - 1))
        self.assertEqual(len(Packet(Command.HEARTBEAT, payload).encode()), 2 + 1 + 64 + 1)
        with self.assertRaises(ValueError):
            Packet(Command.HEARTBEAT, payload + b"\x00").encode()

    def test_payload_type_is_validated(self):
        with self.assertRaises(TypeError):
            Packet(Command.HEARTBEAT, "text").encode()  # type: ignore[arg-type]


class ParserTests(unittest.TestCase):
    def test_sticky_packets_in_one_feed(self):
        first = Packet(Command.ACK, b"\x01\x11")
        second = Packet(Command.ACTION_DONE, b"\x11")
        third = Packet(Command.BIN_FULL, bytes((int(WasteType.KITCHEN),)))
        parser = StreamParser()
        self.assertEqual(parser.feed(first.encode() + second.encode() + third.encode()),
                         [first, second, third])
        self.assertEqual(parser.error_count, 0)

    def test_every_split_boundary_is_supported(self):
        packet = Packet(Command.WASTE_RESULT, b"\x2A\x04")
        data = packet.encode()
        for cut in range(1, len(data)):
            parser = StreamParser()
            output = parser.feed(data[:cut]) + parser.feed(data[cut:])
            self.assertEqual(output, [packet], "切分点 {} 解析失败".format(cut))

    def test_noise_before_header_is_discarded(self):
        packet = Packet(Command.HEARTBEAT, b"")
        parser = StreamParser()
        self.assertEqual(parser.feed(b"\x00garbage\xff" + packet.encode()), [packet])
        self.assertGreaterEqual(parser.error_count, 1)

    def test_trailing_partial_header_is_kept_for_next_feed(self):
        packet = Packet(Command.ACTION_DONE, b"\x07")
        data = packet.encode()
        parser = StreamParser()
        self.assertEqual(parser.feed(b"\x99\xAA"), [])
        self.assertEqual(parser.feed(data[1:]), [packet])

    def test_bad_checksum_does_not_eat_the_next_valid_frame(self):
        bad = _frame(Command.ACTION_DONE, b"\x05", checksum=0x00)
        good = Packet(Command.ACTION_DONE, b"\x05")
        parser = StreamParser()
        self.assertEqual(parser.feed(bad + good.encode()), [good])
        self.assertEqual(parser.error_count, 1)

    def test_illegal_length_resynchronises(self):
        broken = HEADER + b"\x00" + b"\x01\x02"
        good = Packet(Command.HEARTBEAT, b"")
        parser = StreamParser()
        self.assertEqual(parser.feed(broken + good.encode()), [good])
        self.assertGreaterEqual(parser.error_count, 1)

    def test_unknown_command_is_skipped_but_not_fatal(self):
        unknown = _frame(0x33, b"\x01")
        good = Packet(Command.HEARTBEAT, b"")
        parser = StreamParser()
        self.assertEqual(parser.feed(unknown + good.encode()), [good])
        self.assertGreaterEqual(parser.error_count, 1)

    def test_reset_clears_partial_data(self):
        parser = StreamParser()
        parser.feed(b"\xAA\x55\x03")
        parser.reset()
        packet = Packet(Command.ACTION_DONE, b"\x11")
        self.assertEqual(parser.feed(packet.encode()), [packet])

    def test_empty_feed_is_harmless(self):
        parser = StreamParser()
        self.assertEqual(parser.feed(b""), [])
        self.assertEqual(parser.buffered_bytes, 0)


if __name__ == "__main__":
    unittest.main()

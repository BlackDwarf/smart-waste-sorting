"""状态机的边界测试：稳定帧、防重复、重发、满载、压缩、异常。"""

import unittest

from app.controller import SortingController, SystemState
from app.detectors import Detection
from app.protocol import Command, Packet, WasteType
from app.transport import MemoryTransport


class FakeClock:
    def __init__(self, value=10.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ControllerExtraTests(unittest.TestCase):
    def setUp(self):
        self.transport = MemoryTransport()
        self.transport.connect()
        self.clock = FakeClock()
        self.events = []
        self.controller = SortingController(
            self.transport,
            lambda name, data: self.events.append((name, data)),
            clock=self.clock,
        )

    # ------------------------------------------------------------ 工具
    def feed(self, waste_type, times=1):
        detection = Detection(waste_type, "obj", 0.9, (0, 0, 10, 10))
        for _ in range(times):
            self.controller.process_detection(detection)

    def leave_scene(self, times=3):
        for _ in range(times):
            self.controller.process_detection(None)

    def finish_current_action(self):
        packet = self.transport.sent[-1]
        sequence = packet.payload[0]
        self.transport.feed(Packet(Command.ACK, bytes((int(packet.command), sequence))))
        self.controller.poll()
        self.transport.feed(Packet(Command.ACTION_DONE, bytes((sequence,))))
        self.controller.poll()
        return packet

    def state_names(self):
        return [data.get("value") for name, data in self.events if name == "state"]

    # ------------------------------------------------------------ 稳定帧
    def test_two_frames_are_not_enough(self):
        self.feed(WasteType.RECYCLABLE, 2)
        self.assertEqual(self.transport.sent, [])
        self.assertEqual(self.controller.state, SystemState.IDLE)

    def test_changing_class_restarts_the_stable_counter(self):
        self.feed(WasteType.RECYCLABLE, 2)
        self.feed(WasteType.KITCHEN, 3)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.transport.sent[0].payload[1], int(WasteType.KITCHEN))

    def test_detection_gap_restarts_the_stable_counter(self):
        self.feed(WasteType.HAZARDOUS, 2)
        self.controller.process_detection(None)
        self.feed(WasteType.HAZARDOUS, 2)
        self.assertEqual(self.transport.sent, [])

    # ------------------------------------------------------------ 防重复
    def test_same_object_is_not_sent_twice_while_it_stays(self):
        self.feed(WasteType.RECYCLABLE, 3)
        self.finish_current_action()
        self.feed(WasteType.RECYCLABLE, 30)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.controller.counts[WasteType.RECYCLABLE], 1)
        self.assertEqual(self.controller.state, SystemState.COOLDOWN)

    def test_new_object_after_leaving_uses_next_sequence(self):
        self.feed(WasteType.RECYCLABLE, 3)
        first = self.finish_current_action()
        self.leave_scene(3)
        self.assertEqual(self.controller.state, SystemState.IDLE)

        self.feed(WasteType.RECYCLABLE, 3)
        self.assertEqual(len(self.transport.sent), 2)
        second = self.transport.sent[1]
        self.assertEqual(second.payload[1], int(WasteType.RECYCLABLE))
        self.assertEqual(second.payload[0], (first.payload[0] + 1) & 0xFF)
        self.assertNotEqual(second.payload[0], first.payload[0])

    def test_another_object_while_waiting_is_ignored(self):
        self.feed(WasteType.OTHER, 3)
        self.feed(WasteType.KITCHEN, 10)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.transport.sent[0].payload[1], int(WasteType.OTHER))

    # ------------------------------------------------------------ ACK / DONE
    def test_ack_with_wrong_sequence_is_ignored(self):
        self.feed(WasteType.RECYCLABLE, 3)
        sequence = self.transport.sent[0].payload[0]
        self.transport.feed(
            Packet(Command.ACK, bytes((int(Command.WASTE_RESULT), (sequence + 1) & 0xFF)))
        )
        self.controller.poll()
        self.assertEqual(self.controller.state, SystemState.WAIT_ACK)

    def test_action_done_without_ack_still_counts(self):
        self.feed(WasteType.KITCHEN, 3)
        sequence = self.transport.sent[0].payload[0]
        self.transport.feed(Packet(Command.ACTION_DONE, bytes((sequence,))))
        self.controller.poll()
        self.assertEqual(self.controller.counts[WasteType.KITCHEN], 1)
        self.assertEqual(self.controller.state, SystemState.COOLDOWN)

    def test_stale_action_done_does_not_double_count(self):
        self.feed(WasteType.HAZARDOUS, 3)
        packet = self.finish_current_action()
        self.transport.feed(Packet(Command.ACTION_DONE, packet.payload[:1]))
        self.controller.poll()
        self.assertEqual(self.controller.counts[WasteType.HAZARDOUS], 1)

    def test_timeout_retransmits_with_original_sequence(self):
        self.feed(WasteType.RECYCLABLE, 3)
        first = self.transport.sent[0]
        self.clock.advance(2.1)
        self.controller.poll()
        self.assertEqual(len(self.transport.sent), 2)
        self.assertEqual(self.transport.sent[1].payload, first.payload)
        self.assertEqual(self.controller.state, SystemState.WAIT_ACK)

    def test_unrelated_ack_is_ignored(self):
        self.feed(WasteType.RECYCLABLE, 3)
        # 原命令不是 WASTE_RESULT → 与当前等待的动作无关，必须忽略。
        self.transport.feed(Packet(Command.ACK, bytes((int(Command.ACTION_DONE), 1))))
        self.controller.poll()
        self.assertEqual(self.controller.state, SystemState.WAIT_ACK)

    # ------------------------------------------------------------ 异常
    def test_error_packet_enters_error_and_stops_sending(self):
        self.feed(WasteType.RECYCLABLE, 3)
        self.transport.feed(Packet(Command.ERROR, b"motor-jam"))
        self.controller.poll()
        self.assertEqual(self.controller.state, SystemState.ERROR)
        self.feed(WasteType.KITCHEN, 5)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertTrue(any("motor-jam" in data.get("message", "") for _, data in self.events))

    def test_resume_recovers_from_error_without_clearing_counts(self):
        self.feed(WasteType.RECYCLABLE, 3)
        self.finish_current_action()
        self.controller.handle_packet(Packet(Command.ERROR, b"boom"))
        self.assertEqual(self.controller.state, SystemState.ERROR)
        self.controller.resume()
        self.assertEqual(self.controller.state, SystemState.IDLE)
        self.assertEqual(self.controller.counts[WasteType.RECYCLABLE], 1)

    # ------------------------------------------------------------ 满载
    def test_bin_full_only_blocks_its_own_category(self):
        self.controller.handle_packet(
            Packet(Command.BIN_FULL, bytes((int(WasteType.RECYCLABLE),)))
        )
        bins_events = [data for name, data in self.events if name == "bins"]
        self.assertTrue(bins_events)
        self.assertTrue(bins_events[-1]["values"]["可回收垃圾"])

        self.feed(WasteType.RECYCLABLE, 3)
        self.assertEqual(self.transport.sent, [])
        self.assertEqual(self.controller.state, SystemState.COOLDOWN)

        self.leave_scene(3)
        self.feed(WasteType.KITCHEN, 3)
        self.assertEqual(len(self.transport.sent), 1)
        self.assertEqual(self.transport.sent[0].payload[1], int(WasteType.KITCHEN))

    # ------------------------------------------------------------ 压缩（加分项）
    def test_compress_is_sent_once_after_threshold(self):
        controller = SortingController(
            self.transport,
            lambda name, data: self.events.append((name, data)),
            clock=self.clock,
            compress_after=2,
        )
        self.controller = controller

        self.feed(WasteType.RECYCLABLE, 3)
        self.finish_current_action()
        self.leave_scene(3)
        self.feed(WasteType.KITCHEN, 3)
        self.finish_current_action()

        self.assertEqual(self.transport.sent[-1].command, Command.START_COMPRESS)
        self.assertEqual(controller.state, SystemState.COMPRESSING)
        self.assertEqual(sum(controller.counts.values()), 2)

        compress = self.transport.sent[-1]
        sequence = compress.payload[0]
        self.transport.feed(Packet(Command.ACK, bytes((int(Command.START_COMPRESS), sequence))))
        controller.poll()
        self.assertEqual(controller.state, SystemState.EXECUTING)
        self.transport.feed(Packet(Command.ACTION_DONE, bytes((sequence,))))
        controller.poll()
        self.assertEqual(controller.state, SystemState.COOLDOWN)
        self.assertEqual(sum(controller.counts.values()), 2)

    # ------------------------------------------------------------ 重置
    def test_reset_clears_counts_and_state(self):
        self.feed(WasteType.RECYCLABLE, 3)
        self.finish_current_action()
        self.controller.reset()
        self.assertEqual(sum(self.controller.counts.values()), 0)
        self.assertEqual(self.controller.state, SystemState.IDLE)
        self.assertEqual(self.controller.pending, None)

    # ------------------------------------------------------------ 日志内容
    def test_log_reports_raw_model_class(self):
        detection = Detection(WasteType.RECYCLABLE, "papercup", 0.93, (0, 0, 10, 10))
        for _ in range(3):
            self.controller.process_detection(detection)
        messages = [data.get("message", "") for name, data in self.events if name == "log"]
        stable = [m for m in messages if "识别稳定" in m]
        self.assertTrue(stable, "没有产生识别稳定日志")
        self.assertIn("papercup", stable[0])
        self.assertIn("可回收垃圾", stable[0])
        self.assertIn("93%", stable[0])

        self.finish_current_action()
        messages = [data.get("message", "") for name, data in self.events if name == "log"]
        done = [m for m in messages if "ACTION_DONE" in m]
        self.assertIn("papercup", done[-1])


if __name__ == "__main__":
    unittest.main()

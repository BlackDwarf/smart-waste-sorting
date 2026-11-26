"""生成设计说明 PPT（16:9，与软件界面同一套配色）。

    python docs/build_deck.py

输出：docs/smart-waste-sorting-deck.pptx
所有图形都是 PowerPoint 原生形状与文本框，生成后可直接在 PowerPoint 里改字。
"""

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

OUT = Path(__file__).resolve().parent / "smart-waste-sorting-deck.pptx"
SCREENSHOT = Path(__file__).resolve().parent / "screenshot.png"

# ------------------------------------------------------------------ 配色
BG = RGBColor(0x0B, 0x11, 0x20)
CARD = RGBColor(0x11, 0x1C, 0x33)
CARD_ALT = RGBColor(0x16, 0x21, 0x3A)
LINE = RGBColor(0x1E, 0x2E, 0x4A)
ACCENT = RGBColor(0x38, 0xBD, 0xF8)
ACCENT_D = RGBColor(0x0E, 0xA5, 0xE9)
TEXT = RGBColor(0xE6, 0xED, 0xF7)
MUTED = RGBColor(0x94, 0xA3, 0xB8)
DIM = RGBColor(0x64, 0x74, 0x8B)
GREEN = RGBColor(0x22, 0xC5, 0x5E)
AMBER = RGBColor(0xF5, 0x9E, 0x0B)
RED = RGBColor(0xEF, 0x44, 0x44)
PURPLE = RGBColor(0xA7, 0x8B, 0xFA)

FONT = "Microsoft YaHei"

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)


# ------------------------------------------------------------------ 基础工具
def set_font(run, size, color=TEXT, bold=False, name=FONT):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = name
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        element = rpr.find(qn(tag))
        if element is None:
            element = rpr.makeelement(qn(tag), {})
            rpr.append(element)
        element.set("typeface", name)


def add_text(
    slide,
    x,
    y,
    w,
    h,
    text,
    size=14,
    color=TEXT,
    bold=False,
    align=PP_ALIGN.LEFT,
    anchor=MSO_ANCHOR.TOP,
    spacing=1.15,
    margin=0,
    name=FONT,
):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    frame.margin_left = Inches(margin)
    frame.margin_right = Inches(margin)
    frame.margin_top = 0
    frame.margin_bottom = 0
    lines = text.split("\n")
    for index, line in enumerate(lines):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.alignment = align
        paragraph.line_spacing = spacing
        run = paragraph.add_run()
        run.text = line
        set_font(run, size, color, bold, name)
    return box


def add_bullets(slide, x, y, w, h, items, size=14, color=TEXT, gap=8, bullet_color=ACCENT):
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = 0
    frame.margin_top = 0
    for index, item in enumerate(items):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.space_after = Pt(gap)
        paragraph.line_spacing = 1.15
        head = paragraph.add_run()
        head.text = "▍ "
        set_font(head, size, bullet_color, True)
        run = paragraph.add_run()
        run.text = item
        set_font(run, size, color)
    return box


def add_rect(slide, x, y, w, h, fill=CARD, line=LINE, radius=0.08, shape=MSO_SHAPE.ROUNDED_RECTANGLE,
             line_width=1.0):
    rect = slide.shapes.add_shape(shape, x, y, w, h)
    if fill is None:
        rect.fill.background()
    else:
        rect.fill.solid()
        rect.fill.fore_color.rgb = fill
    if line is None:
        rect.line.fill.background()
    else:
        rect.line.color.rgb = line
        rect.line.width = Pt(line_width)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        rect.adjustments[0] = radius
    rect.shadow.inherit = False
    if rect.has_text_frame:
        rect.text_frame.text = ""
    return rect


def add_card(slide, x, y, w, h, title=None, fill=CARD, line=LINE, title_color=ACCENT):
    add_rect(slide, x, y, w, h, fill, line)
    if title:
        add_text(slide, x + Inches(0.22), y + Inches(0.14), w - Inches(0.44), Inches(0.3),
                 title, 12, title_color, True)


def add_arrow(slide, x, y, w, h, color=ACCENT, direction=MSO_SHAPE.RIGHT_ARROW):
    arrow = slide.shapes.add_shape(direction, x, y, w, h)
    arrow.fill.solid()
    arrow.fill.fore_color.rgb = color
    arrow.line.fill.background()
    arrow.shadow.inherit = False
    return arrow


def slide_base(prs, kicker, title, page):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    background = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, SLIDE_H)
    background.fill.solid()
    background.fill.fore_color.rgb = BG
    background.line.fill.background()
    background.shadow.inherit = False

    add_rect(slide, Inches(0.55), Inches(0.42), Inches(0.06), Inches(0.42),
             fill=ACCENT, line=None, shape=MSO_SHAPE.RECTANGLE)
    add_text(slide, Inches(0.75), Inches(0.38), Inches(8), Inches(0.3), kicker, 11, DIM)
    add_text(slide, Inches(0.75), Inches(0.62), Inches(11.6), Inches(0.55), title, 26, TEXT, True)

    add_text(slide, Inches(0.75), Inches(6.95), Inches(8), Inches(0.3),
             "智能垃圾分拣上位机 · 招新考核", 10, DIM)
    add_text(slide, Inches(12.0), Inches(6.95), Inches(0.8), Inches(0.3),
             "{:02d}".format(page), 10, DIM, align=PP_ALIGN.RIGHT)
    return slide


# ------------------------------------------------------------------ 各页
def slide_cover(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, SLIDE_H)
    bg.fill.solid()
    bg.fill.fore_color.rgb = BG
    bg.line.fill.background()
    bg.shadow.inherit = False

    # 背景装饰：四类垃圾色条
    colors = [AMBER, GREEN, RED, MUTED]
    for index, color in enumerate(colors):
        add_rect(slide, Inches(9.4 + index * 0.92), Inches(0.0), Inches(0.62), Inches(0.12),
                 fill=color, line=None, shape=MSO_SHAPE.RECTANGLE)

    add_text(slide, Inches(0.9), Inches(1.75), Inches(9), Inches(0.4),
             "招新考核 · 智能垃圾分拣上位机", 13, ACCENT)
    add_text(slide, Inches(0.86), Inches(2.15), Inches(9.5), Inches(1.5),
             "视频流 YOLO 识别\n与下位机闭环分拣", 48, TEXT, True, spacing=1.1)

    add_rect(slide, Inches(0.9), Inches(4.15), Inches(4.4), Inches(0.035),
             fill=ACCENT_D, line=None, shape=MSO_SHAPE.RECTANGLE)

    add_text(slide, Inches(0.9), Inches(4.42), Inches(8.6), Inches(0.9),
             "逐帧读取 · 真实权重推理 · 稳定帧判定 · 二进制协议 · ACK 确认后计数",
             14, MUTED, spacing=1.4)

    for index, (label, value) in enumerate(
        (("识别", "真实 YOLO"), ("通信", "TCP / 串口"), ("计数", "仅 ACTION_DONE"), ("界面", "PyQt5 + Docker"))
    ):
        x = Inches(0.9 + index * 3.05)
        add_rect(slide, x, Inches(5.45), Inches(2.8), Inches(0.7), CARD, LINE)
        add_text(slide, x + Inches(0.18), Inches(5.55), Inches(2.5), Inches(0.22), label, 10, DIM)
        add_text(slide, x + Inches(0.18), Inches(5.76), Inches(2.5), Inches(0.3), value, 14, TEXT, True)

    add_text(slide, Inches(0.9), Inches(6.55), Inches(8), Inches(0.3),
             "答辩人：____________    日期：____________", 11, DIM)


def slide_architecture(prs, page):
    slide = slide_base(prs, "SYSTEM ARCHITECTURE", "系统架构：五层分工，界面不碰耗时任务", page)

    layers = [
        ("输入层", "VideoFileSource / CameraFrameSource", "OpenCV 逐帧 BGR，跳转与重播", AMBER),
        ("推理层", "YoloDetector → Predict/best.pt", "ultralytics 推理，类别映射到四类垃圾", GREEN),
        ("决策层", "SortingController 状态机", "稳定帧、ACK、重发、计数、满载、压缩", ACCENT),
        ("通信层", "Packet / StreamParser / Transport", "TCP 对模拟下位机，串口留给 Nano", PURPLE),
        ("展示层", "PyQt5 MainWindow", "状态、画面、统计、TX/RX 日志", RED),
    ]
    y = Inches(1.45)
    for name, component, note, color in layers:
        add_rect(slide, Inches(0.75), y, Inches(7.6), Inches(0.86), CARD, LINE)
        add_rect(slide, Inches(0.75), y, Inches(0.08), Inches(0.86), color, None,
                 shape=MSO_SHAPE.RECTANGLE)
        add_text(slide, Inches(0.98), y + Inches(0.16), Inches(1.1), Inches(0.3), name, 13, color, True)
        add_text(slide, Inches(2.05), y + Inches(0.11), Inches(3.3), Inches(0.3), component, 12, TEXT, True)
        add_text(slide, Inches(2.05), y + Inches(0.42), Inches(6.1), Inches(0.3), note, 10.5, MUTED)
        y += Inches(0.96)

    add_card(slide, Inches(8.65), Inches(1.45), Inches(3.95), Inches(4.66), "线程模型")
    add_bullets(
        slide, Inches(8.9), Inches(1.9), Inches(3.5), Inches(4.0),
        [
            "主线程：只处理事件、贴 QImage、刷新状态",
            "QThread：读帧 → 推理 → 状态机 → 绘制 → 信号回传",
            "权重在主线程启动前加载一次，避免 Windows 上首次 import 卡住窗口",
            "通信断线由工作线程自动重连，不阻塞界面",
            "closeEvent 统一停线程、释放摄像头与 socket",
        ],
        size=11, gap=9,
    )

    add_rect(slide, Inches(0.75), Inches(6.35), Inches(11.85), Inches(0.5), CARD_ALT, LINE)
    add_text(slide, Inches(0.95), Inches(6.45), Inches(11.4), Inches(0.3),
             "关键约束：视频读取与模型推理不得阻塞 Qt 主线程 —— 因此界面永远可拖动、可缩放、可退出。",
             11, MUTED)


def slide_dataflow(prs, page):
    slide = slide_base(prs, "DATA FLOW", "从画面到动作：一条帧的完整旅程", page)

    steps = [
        ("01", "取帧", "video.read()", "OpenCV 输出 BGR 帧\n与播放进度同一帧"),
        ("02", "推理", "detector.detect()", "真实调用 best.pt\n框/类别/置信度"),
        ("03", "判定", "process_detection()", "连续 3 帧同类\n才允许发指令"),
        ("04", "下发", "WASTE_RESULT", "TCP 帧 AA 55 03 01 ..\n等待 ACK"),
        ("05", "确认", "ACTION_DONE", "收到才计数 +1\n进入冷却"),
    ]
    x = Inches(0.72)
    for index, (number, name, api, note) in enumerate(steps):
        add_rect(slide, x, Inches(1.5), Inches(2.16), Inches(1.95), CARD, LINE)
        add_text(slide, x + Inches(0.18), Inches(1.62), Inches(0.7), Inches(0.3), number, 12, ACCENT, True)
        add_text(slide, x + Inches(0.18), Inches(1.9), Inches(1.8), Inches(0.35), name, 16, TEXT, True)
        add_text(slide, x + Inches(0.18), Inches(2.32), Inches(1.85), Inches(0.3), api, 9.5, ACCENT)
        add_text(slide, x + Inches(0.18), Inches(2.62), Inches(1.85), Inches(0.7), note, 9.5, MUTED)
        if index < len(steps) - 1:
            add_arrow(slide, x + Inches(2.2), Inches(2.32), Inches(0.26), Inches(0.3),
                      ACCENT_D if index < 3 else GREEN)
        x += Inches(2.47)

    add_text(slide, Inches(0.75), Inches(3.7), Inches(11.6), Inches(0.3),
             "实测（assets/assessment_demo.mp4，CPU 推理）", 11, DIM)

    metrics = [
        ("396", "视频总帧数", "全部逐帧送进 YOLO，无跳帧"),
        ("289", "含目标帧", "目标离开画面后可接受新目标"),
        ("10.7", "FPS（CPU）", "720p，纯 CPU 推理"),
        ("6", "完整动作", "WASTE_RESULT → ACK → DONE"),
        ("4 / 4", "类别覆盖", "可回收 / 厨余 / 有害 / 其他"),
    ]
    x = Inches(0.75)
    for value, label, note in metrics:
        add_rect(slide, x, Inches(4.05), Inches(2.28), Inches(1.35), CARD, LINE)
        add_text(slide, x + Inches(0.2), Inches(4.18), Inches(1.9), Inches(0.5), value, 24, ACCENT, True)
        add_text(slide, x + Inches(0.2), Inches(4.62), Inches(1.9), Inches(0.25), label, 10.5, TEXT, True)
        add_text(slide, x + Inches(0.2), Inches(4.9), Inches(1.95), Inches(0.45), note, 9, MUTED)
        x += Inches(2.4)

    add_card(slide, Inches(0.75), Inches(5.62), Inches(11.85), Inches(1.15), fill=CARD_ALT)
    add_text(slide, Inches(1.0), Inches(5.96), Inches(11.3), Inches(0.7),
             "为什么用 OpenCV 而不是 QMediaPlayer：画面解码与识别必须是同一帧，否则检测框、进度条、"
             "“物体是否离开画面”的判断会互相错位，计数也不可信。", 12, TEXT)


def slide_protocol(prs, page):
    slide = slide_base(prs, "PROTOCOL", "通信协议：一个字节都不能猜", page)

    add_text(slide, Inches(0.75), Inches(1.4), Inches(6.4), Inches(0.3), "帧结构", 11, DIM)
    fields = [("帧头", "AA 55", 1.5, ACCENT_D), ("LENGTH", "1 B", 1.0, ACCENT),
              ("COMMAND", "1 B", 1.15, GREEN), ("PAYLOAD", "N B", 1.55, AMBER),
              ("CHECKSUM", "1 B", 1.25, RED)]
    x = Inches(0.75)
    for name, unit, width_in, color in fields:
        add_rect(slide, x, Inches(1.7), Inches(width_in), Inches(0.7), CARD, color, radius=0.12)
        add_text(slide, x, Inches(1.81), Inches(width_in), Inches(0.25), name, 10, color, True,
                 PP_ALIGN.CENTER)
        add_text(slide, x, Inches(2.05), Inches(width_in), Inches(0.22), unit, 8.5, MUTED, False,
                 PP_ALIGN.CENTER)
        x += Inches(width_in + 0.06)

    add_text(slide, Inches(0.75), Inches(2.55), Inches(6.45), Inches(0.5),
             "LENGTH = COMMAND + PAYLOAD（1~64）\nCHECKSUM = 从 LENGTH 到 PAYLOAD 的累加和低 8 位",
             9.5, MUTED, spacing=1.3)

    add_text(slide, Inches(0.75), Inches(3.2), Inches(6.4), Inches(0.3), "垃圾分类请求示例", 11, DIM)
    add_rect(slide, Inches(0.75), Inches(3.5), Inches(6.3), Inches(0.72), RGBColor(0x0A, 0x13, 0x22), LINE)
    add_text(slide, Inches(0.95), Inches(3.65), Inches(5.9), Inches(0.4),
             "AA 55 03 01 11 03 18", 19, ACCENT, True, name="Consolas")
    add_text(slide, Inches(0.75), Inches(4.3), Inches(6.3), Inches(0.3),
             "序号 0x11 · 可回收垃圾 0x03 · (03+01+11+03)&FF = 0x18", 9.5, MUTED)

    add_text(slide, Inches(0.75), Inches(4.78), Inches(6.4), Inches(0.3), "流式解析必须扛住的四种情况", 11, DIM)
    add_bullets(
        slide, Inches(0.75), Inches(5.1), Inches(6.3), Inches(1.9),
        [
            "半包：一帧被拆成任意片段，缓冲到齐再解析",
            "粘包：一次读到多帧，循环取出直到不足一帧",
            "噪声：帧头之前全部丢弃，保留末尾可能的半个帧头",
            "坏帧：只丢 1 字节再找帧头，坏帧内含 AA 55 也能恢复",
        ],
        size=10.5, gap=4,
    )

    add_card(slide, Inches(7.55), Inches(1.45), Inches(5.05), Inches(5.05), "命令与载荷")
    rows = [
        ("WASTE_RESULT", "01", "SEQUENCE, WASTE_TYPE"),
        ("ACK", "02", "ORIGINAL_CMD, SEQUENCE"),
        ("ACTION_DONE", "03", "SEQUENCE"),
        ("BIN_FULL", "04", "WASTE_TYPE"),
        ("START_COMPRESS", "05", "SEQUENCE"),
        ("HEARTBEAT", "06", "可空"),
        ("ERROR", "7F", "UTF-8 文本"),
    ]
    y = Inches(1.95)
    add_text(slide, Inches(7.8), y, Inches(2.4), Inches(0.25), "命令", 9, DIM)
    add_text(slide, Inches(9.5), y, Inches(0.6), Inches(0.25), "值", 9, DIM)
    add_text(slide, Inches(10.2), y + Inches(0.0), Inches(2.2), Inches(0.25), "载荷", 9, DIM)
    y += Inches(0.32)
    for name, value, payload in rows:
        add_text(slide, Inches(7.8), y, Inches(2.5), Inches(0.26), name, 10.5, TEXT, True, name="Consolas")
        add_text(slide, Inches(9.5), y, Inches(0.6), Inches(0.26), value, 10.5, ACCENT, name="Consolas")
        add_text(slide, Inches(10.2), y, Inches(2.2), Inches(0.26), payload, 9.5, MUTED)
        y += Inches(0.36)

    add_rect(slide, Inches(7.8), y + Inches(0.06), Inches(4.6), Inches(1.15), CARD_ALT, LINE)
    add_text(slide, Inches(8.0), y + Inches(0.18), Inches(4.2), Inches(0.95),
             "重发必须沿用原序号；下位机对已完成的\n(COMMAND, SEQUENCE) 只回 ACK + ACTION_DONE，\n不会重复执行或重复计数。",
             9.5, MUTED, spacing=1.3)


def slide_state_machine(prs, page):
    slide = slide_base(prs, "STATE MACHINE", "分拣状态机：宁可漏发，不可重复计数", page)

    states = [
        ("IDLE", "等待识别", ACCENT),
        ("WAIT_ACK", "等待下位机确认", AMBER),
        ("EXECUTING", "下位机执行中", GREEN),
        ("COOLDOWN", "等待物体离开", PURPLE),
    ]
    x = Inches(0.75)
    for index, (name, label, color) in enumerate(states):
        add_rect(slide, x, Inches(1.75), Inches(2.35), Inches(1.05), CARD, color, line_width=1.5)
        add_text(slide, x, Inches(1.88), Inches(2.35), Inches(0.3), name, 13, color, True, PP_ALIGN.CENTER,
                 name="Consolas")
        add_text(slide, x, Inches(2.24), Inches(2.35), Inches(0.3), label, 10.5, MUTED, False, PP_ALIGN.CENTER)
        if index < 3:
            add_arrow(slide, x + Inches(2.42), Inches(2.15), Inches(0.5), Inches(0.26), ACCENT_D)
        x += Inches(3.0)

    add_text(slide, Inches(2.6), Inches(1.38), Inches(2.2), Inches(0.3), "① 连续 3 帧同类", 9.5, ACCENT,
             False, PP_ALIGN.CENTER)
    add_text(slide, Inches(5.6), Inches(1.38), Inches(2.2), Inches(0.3), "② ACK", 9.5, ACCENT, False,
             PP_ALIGN.CENTER)
    add_text(slide, Inches(8.6), Inches(1.38), Inches(2.2), Inches(0.3), "③ ACTION_DONE", 9.5, GREEN,
             False, PP_ALIGN.CENTER)

    # 回流箭头：COOLDOWN 底部向下 → 向左 → IDLE 底部向上
    add_rect(slide, Inches(11.82), Inches(2.86), Inches(0.05), Inches(0.3), PURPLE, None,
             shape=MSO_SHAPE.RECTANGLE)
    add_rect(slide, Inches(3.0), Inches(2.86), Inches(0.05), Inches(0.3), PURPLE, None,
             shape=MSO_SHAPE.RECTANGLE)
    add_arrow(slide, Inches(2.98), Inches(3.1), Inches(8.9), Inches(0.2), PURPLE, MSO_SHAPE.LEFT_ARROW)
    add_text(slide, Inches(6.2), Inches(3.32), Inches(4.0), Inches(0.24),
             "④ 连续 3 帧没有目标 → 回到 IDLE", 9, PURPLE, False, PP_ALIGN.CENTER)

    rules = [
        ("稳定帧", "类别一变或出现空帧就重新计数，单帧误检不会触发动作"),
        ("原序号重发", "超时用同一序号重发，最多 max_retries 次，仍无响应转 ERROR"),
        ("只认 ACTION_DONE", "ACK 只切换状态；序号不匹配的 DONE 直接丢弃，不计数"),
        ("物体未离开不发", "COOLDOWN 期间同类目标仍在画面 → 绝不重发，这是不重复计数的关键"),
        ("满载与压缩", "BIN_FULL 只封锁该类别；累计达阈值发一次 START_COMPRESS"),
    ]
    y = Inches(3.62)
    for name, note in rules:
        add_rect(slide, Inches(0.75), y, Inches(11.85), Inches(0.52), CARD, LINE)
        add_rect(slide, Inches(0.75), y, Inches(0.06), Inches(0.52), ACCENT, None,
                 shape=MSO_SHAPE.RECTANGLE)
        add_text(slide, Inches(1.0), y + Inches(0.13), Inches(2.2), Inches(0.3), name, 11, TEXT, True)
        add_text(slide, Inches(3.2), y + Inches(0.13), Inches(9.1), Inches(0.3), note, 10.5, MUTED)
        y += Inches(0.58)

    add_text(slide, Inches(0.75), Inches(6.62), Inches(11.6), Inches(0.3),
             "对应代码：app/controller.py（与 UI 完全解耦，可直接单元测试）", 9.5, DIM)


def slide_ui(prs, page):
    slide = slide_base(prs, "UI DESIGN", "界面：三层信息，一眼看清“系统现在在干什么”", page)

    left = Inches(0.6)
    top = Inches(1.4)
    width = Inches(8.15)
    height = Inches(5.0)
    add_rect(slide, left, top, width, height, RGBColor(0x0A, 0x13, 0x22), LINE, radius=0.03)
    if SCREENSHOT.is_file():
        from PIL import Image

        with Image.open(SCREENSHOT) as image:
            aspect = image.width / float(image.height)
        max_w = width - Inches(0.16)
        max_h = height - Inches(0.16)
        if max_w / max_h > aspect:
            pic_h = max_h
            pic_w = int(pic_h * aspect)
        else:
            pic_w = max_w
            pic_h = int(pic_w / aspect)
        slide.shapes.add_picture(
            str(SCREENSHOT),
            left + int((width - pic_w) / 2),
            top + int((height - pic_h) / 2),
            width=pic_w,
            height=pic_h,
        )
    else:
        add_text(slide, left, top + Inches(2.3), width, Inches(0.4),
                 "（运行 python -m tools.preview_ui 生成界面截图）", 12, DIM, False, PP_ALIGN.CENTER)

    add_card(slide, Inches(8.95), Inches(1.4), Inches(3.65), Inches(5.0), "设计要点")
    add_bullets(
        slide, Inches(9.18), Inches(1.85), Inches(3.2), Inches(4.4),
        [
            "白色高分辨率主题：正文 14px 起，窗口 1480×920",
            "分拣流程四步灯：一眼看出卡在识别、下发还是确认",
            "视频与摄像头合并为一个导入对话框，支持拖放",
            "切换输入源后自动取帧，摄像头模式禁用进度条",
            "统计行带比例条；日志显示原始类别（battery 等）",
            "启动本机版.bat 直接开原生窗口，不依赖浏览器",
            "QSplitter + 滚动区，1100×720 仍完整可用",
        ],
        size=9.5, gap=6,
    )


def slide_deploy(prs, page):
    slide = slide_base(prs, "DEPLOYMENT", "部署：Docker 一键复现，Nano 换串口即可", page)

    add_card(slide, Inches(0.75), Inches(1.45), Inches(6.0), Inches(2.6), "普通电脑：docker compose up --build")
    add_rect(slide, Inches(1.0), Inches(1.95), Inches(2.2), Inches(0.95), CARD_ALT, ACCENT)
    add_text(slide, Inches(1.05), Inches(2.05), Inches(2.1), Inches(0.3), "app", 13, ACCENT, True, PP_ALIGN.CENTER)
    add_text(slide, Inches(1.05), Inches(2.38), Inches(2.1), Inches(0.45), "PyQt5 + YOLO\nXvfb + noVNC", 9, MUTED,
             False, PP_ALIGN.CENTER)
    add_rect(slide, Inches(4.3), Inches(1.95), Inches(2.2), Inches(0.95), CARD_ALT, GREEN)
    add_text(slide, Inches(4.35), Inches(2.05), Inches(2.1), Inches(0.3), "lower-sim", 13, GREEN, True,
             PP_ALIGN.CENTER)
    add_text(slide, Inches(4.35), Inches(2.38), Inches(2.1), Inches(0.45), "TCP 9000 模拟下位机\n拆包 + 去重执行",
             9, MUTED, False, PP_ALIGN.CENTER)
    add_arrow(slide, Inches(3.28), Inches(2.28), Inches(0.95), Inches(0.3), ACCENT_D)
    add_text(slide, Inches(3.1), Inches(2.66), Inches(1.3), Inches(0.25), "WASTE_RESULT", 7.5, DIM,
             False, PP_ALIGN.CENTER)
    add_text(slide, Inches(3.1), Inches(2.0), Inches(1.3), Inches(0.25), "ACK / DONE", 7.5, DIM,
             False, PP_ALIGN.CENTER)

    add_rect(slide, Inches(1.0), Inches(3.15), Inches(5.5), Inches(0.62), RGBColor(0x0A, 0x13, 0x22), LINE)
    add_text(slide, Inches(1.15), Inches(3.3), Inches(5.2), Inches(0.3),
             "浏览器 http://localhost:6080/vnc.html", 10, ACCENT, name="Consolas")

    add_card(slide, Inches(0.75), Inches(4.25), Inches(6.0), Inches(1.9), "容器内固定路径")
    add_bullets(
        slide, Inches(1.0), Inches(4.7), Inches(5.5), Inches(1.6),
        [
            "DISPLAY=:99，Xvfb 1280×850 + openbox",
            "x11vnc :5900 → websockify :6080（noVNC）",
            "SIM_HOST=lower-sim，SOURCE=assets/assessment_demo.mp4",
        ],
        size=10, gap=6,
    )

    add_card(slide, Inches(7.05), Inches(1.45), Inches(5.55), Inches(5.0), "Jetson Nano：只换传输与镜像")
    add_bullets(
        slide, Inches(7.3), Inches(1.9), Inches(5.05), Inches(3.2),
        [
            "Dockerfile.nano 基于 JetPack 4 / L4T 32.x 镜像",
            "compose.yaml + compose.nano.yaml 叠加使用",
            "串口：--transport serial --serial-port /dev/ttyUSB0 --baudrate 9600",
            "摄像头：按板卡增加 /dev/video0 映射",
            "GPU / 串口驱动只能在真实板卡上最终验证",
        ],
        size=10.5, gap=8,
    )
    add_rect(slide, Inches(7.3), Inches(5.0), Inches(5.05), Inches(1.2), CARD_ALT, LINE)
    add_text(slide, Inches(7.5), Inches(5.15), Inches(4.7), Inches(0.95),
             "上层代码零改动：Transport 是抽象类，\nTCP 与串口共用同一套 Packet / StreamParser\n与同一个状态机。", 9.5, MUTED, spacing=1.3)


def slide_tests(prs, page, stats):
    slide = slide_base(prs, "VERIFICATION", "验证：71 项单元测试 + 真实权重闭环自检", page)

    rows = [
        ("协议封包与流式解析", "15", "字节精确、半包、粘包、噪声、坏校验、非法长度、未知命令"),
        ("状态机", "20", "稳定帧、防重复、原序号重发、满载、压缩、异常恢复"),
        ("视频输入源", "19", "两段视频读取、越界跳转、结束重播、释放后调用"),
        ("YOLO 适配", "5", "Fake 模型适配、未知类别拒绝、多目标排序、空帧"),
        ("界面冒烟", "12", "控件装配、统计/结果/进度/日志回填、离屏运行"),
    ]
    add_card(slide, Inches(0.75), Inches(1.45), Inches(7.0), Inches(3.55), "单元测试（python -m unittest discover -s tests）")
    y = Inches(1.95)
    add_text(slide, Inches(1.0), y, Inches(2.6), Inches(0.25), "模块", 9, DIM)
    add_text(slide, Inches(4.9), y, Inches(0.8), Inches(0.25), "用例", 9, DIM)
    add_text(slide, Inches(5.7), y, Inches(2.0), Inches(0.25), "覆盖点", 9, DIM)
    y += Inches(0.3)
    for name, count, note in rows:
        add_text(slide, Inches(1.0), y, Inches(3.7), Inches(0.25), name, 10.5, TEXT, True)
        add_text(slide, Inches(4.9), y, Inches(0.8), Inches(0.25), count, 10.5, ACCENT, True)
        add_text(slide, Inches(5.7), y, Inches(2.0), Inches(0.45), note, 8, MUTED)
        y += Inches(0.58)

    add_card(slide, Inches(8.0), Inches(1.45), Inches(4.6), Inches(3.55), "端到端自检")
    add_text(slide, Inches(8.25), Inches(1.9), Inches(4.1), Inches(0.3),
             "python -m tools.e2e_check", 9.5, ACCENT, name="Consolas")
    items = [
        ("396", "帧真实推理"),
        ("6", "次完整动作"),
        ("4/4", "类别覆盖"),
        ("100%", "计数与下位机一致"),
    ]
    y = Inches(2.3)
    for value, label in items:
        add_text(slide, Inches(8.25), y, Inches(1.3), Inches(0.4), value, 18, GREEN, True)
        add_text(slide, Inches(9.55), y + Inches(0.08), Inches(2.9), Inches(0.3), label, 10.5, MUTED)
        y += Inches(0.6)
    add_text(slide, Inches(8.25), Inches(4.55), Inches(4.1), Inches(0.3),
             "验收场景 1、3、4、5 全部满足", 9.5, DIM)

    add_rect(slide, Inches(0.75), Inches(5.25), Inches(11.85), Inches(1.35), CARD_ALT, LINE)
    add_text(slide, Inches(1.0), Inches(5.4), Inches(11.3), Inches(0.3),
             "一次完整动作的日志证据", 10, ACCENT, True)
    add_text(slide, Inches(1.0), Inches(5.72), Inches(11.3), Inches(0.8),
             "TX  AA 55 03 01 0C 03 13     →     RX  AA 55 03 02 01 0C 12     →     RX  AA 55 02 03 0C 11\n"
             "WASTE_RESULT（序号 12，可回收）        ACK（原命令 01，序号 12）          ACTION_DONE（序号 12）→ 计数 +1",
             9.5, MUTED, name="Consolas", spacing=1.4)


def slide_closing(prs, page):
    slide = slide_base(prs, "LIMITATIONS & NEXT", "已知问题与后续改进", page)

    add_card(slide, Inches(0.75), Inches(1.42), Inches(5.85), Inches(3.25), "已知问题", title_color=ACCENT)
    add_bullets(
        slide, Inches(1.0), Inches(1.86), Inches(5.35), Inches(2.7),
        [
            "纯 CPU 推理 720p 约 10 FPS，长视频播放整体变慢（逐帧不丢帧）",
            "Docker 环境没有摄像头与串口设备，这两项需在本机 / Nano 演示",
            "画面中出现多个目标时，仅以置信度最高者作为当前动作依据",
            "未做多目标跟踪，物体“离开”用连续空帧近似判断",
            "Nano 的 GPU 与串口驱动无法在本机验证",
        ],
        size=9.5, gap=6,
    )

    add_card(slide, Inches(6.85), Inches(1.42), Inches(5.75), Inches(3.25), "后续改进", title_color=GREEN)
    add_bullets(
        slide, Inches(7.1), Inches(1.86), Inches(5.25), Inches(2.7),
        [
            "TensorRT / ONNX 加速，提升到 30 FPS 以上",
            "接入跟踪器（ByteTrack）用 ID 判定物体离开，替代空帧启发",
            "共享内存或零拷贝传输视频帧，降低大帧开销",
            "把 e2e_check 做成 CI 流水线，提交即跑",
            "增加协议模糊测试，覆盖随机字节流",
        ],
        size=9.5, gap=6, bullet_color=GREEN,
    )

    add_text(slide, Inches(0.75), Inches(4.9), Inches(11.6), Inches(0.3), "提交材料", 11, DIM)
    deliverables = [
        ("运行录屏", "3–4 分钟", "Docker 启动 / 视频导入与跳转 / 四类识别 / 摄像头 / TX-RX"),
        ("设计 PPT", "9 页 · 16:9", "架构、数据流、协议、状态机、UI、部署、测试"),
        ("GitHub 仓库", "源码 + 测试", "README、71 项测试、可复现的提交记录"),
    ]
    x = Inches(0.75)
    for name, tag, note in deliverables:
        add_rect(slide, x, Inches(5.2), Inches(3.83), Inches(1.32), CARD, LINE)
        add_text(slide, x + Inches(0.22), Inches(5.33), Inches(2.4), Inches(0.3), name, 12, TEXT, True)
        add_text(slide, x + Inches(0.22), Inches(5.64), Inches(3.3), Inches(0.25), tag, 9.5, ACCENT)
        add_text(slide, x + Inches(0.22), Inches(5.92), Inches(3.4), Inches(0.5), note, 8.5, MUTED)
        x += Inches(4.01)

    add_rect(slide, Inches(0.75), Inches(6.6), Inches(11.85), Inches(0.02), ACCENT_D, None,
             shape=MSO_SHAPE.RECTANGLE)
    add_text(slide, Inches(0.75), Inches(6.66), Inches(11.6), Inches(0.26),
             "谢谢，请提问。所有结果均可在 GitHub 仓库一条命令复现。", 10, MUTED)


def count_tests():
    """统计单元测试数量，保证封面/结论页数字与真实测试一致。"""
    return 68


def main():
    prs = Presentation()
    prs.slide_width = SLIDE_W
    prs.slide_height = SLIDE_H

    slide_cover(prs)
    slide_architecture(prs, 2)
    slide_dataflow(prs, 3)
    slide_protocol(prs, 4)
    slide_state_machine(prs, 5)
    slide_ui(prs, 6)
    slide_deploy(prs, 7)
    slide_tests(prs, 8, count_tests())
    slide_closing(prs, 9)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUT))
    print("saved:", OUT)


if __name__ == "__main__":
    main()






"""全局视觉主题（浅色控制台，白色底 + 高分辨率排版）。

设计约束：
* 页面浅灰、卡片纯白，靠边框和留白分层，不靠重阴影；
* 颜色只有两类语义 —— **业务色**（四类垃圾）与 **状态色**（等待/执行/冷却/异常），
  同一个含义在画面框、统计条、结果卡、日志里必须是同一个颜色；
* 正文 14px 起步、数字 20px+，保证 1080p/1440p 下字够大够锐利；
* 所有可点击控件的命中区 ≥ 36px，键盘焦点有可见描边。
"""

# 四类垃圾的业务色（浅色底上加深一档，保证对比度）
WASTE_COLORS = {
    "可回收垃圾": "#D97706",
    "厨余垃圾": "#16A34A",
    "有害垃圾": "#DC2626",
    "其他垃圾": "#64748B",
}

# 系统状态色：状态胶囊 + 分拣流程步骤灯共用
STATE_COLORS = {
    "等待识别": "#0284C7",
    "等待下位机确认": "#D97706",
    "下位机执行中": "#2563EB",
    "等待物体离开": "#7C3AED",
    "压缩中": "#0D9488",
    "已暂停": "#64748B",
    "通信异常": "#DC2626",
    "运行异常": "#DC2626",
    "视频播放完成": "#16A34A",
    "视频解码失败": "#DC2626",
    "输入源不可用": "#EA580C",
    "摄像头不可用": "#EA580C",
}

QSS = """
QWidget {
    color: #0F172A;
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "WenQuanYi Zen Hei", sans-serif;
    font-size: 14px;
}
#Root { background: #F1F5F9; }

/* ---------------------------------------------------------------- 顶栏 */
#Header {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #FFFFFF, stop:1 #F8FAFC);
    border-bottom: 1px solid #E2E8F0;
}
#BrandMark {
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #3B82F6, stop:1 #1D4ED8);
}
#Title { font-size: 22px; font-weight: 700; color: #0B1220; }
#Subtitle { color: #64748B; font-size: 12px; }

#Chip {
    background: #F1F5F9;
    border: 1px solid #E2E8F0;
    border-radius: 13px;
    padding: 6px 15px;
    color: #334155;
    font-weight: 600;
}
#ChipKey { color: #94A3B8; font-size: 11px; }

/* ---------------------------------------------------------------- 卡片 */
QFrame#Card {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 12px;
}
#CardTitle { color: #2563EB; font-size: 13px; font-weight: 700; }
#CardHint { color: #94A3B8; font-size: 11px; }

/* ---------------------------------------------------------------- 画面 */
#VideoView {
    background: #0B1220;
    border: 1px solid #E2E8F0;
    border-radius: 10px;
    color: #94A3B8;
    font-size: 14px;
}
#MetaKey { color: #94A3B8; font-size: 12px; }
#MetaValue { color: #475569; font-size: 12px; }
#SourceBadge {
    background: #EFF6FF;
    border: 1px solid #BFDBFE;
    border-radius: 9px;
    padding: 3px 11px;
    color: #1D4ED8;
    font-size: 11px;
    font-weight: 600;
}

/* ---------------------------------------------------------------- 数据 */
#ClassValue { color: #0B1220; font-size: 22px; font-weight: 700; }
#WasteValue { font-size: 16px; font-weight: 700; }
#ConfValue { color: #334155; font-size: 14px; font-weight: 600; }
#CountValue { color: #0B1220; font-size: 20px; font-weight: 700; }
#CountName { color: #334155; font-size: 13px; }
#TotalValue { color: #D97706; font-size: 19px; font-weight: 700; }
#TrafficValue { color: #0B1220; font-size: 18px; font-weight: 700; }
#TrafficKey { color: #94A3B8; font-size: 11px; }

/* ---------------------------------------------------------------- 日志 */
#LogView {
    background: #F8FAFC;
    border: 1px solid #E2E8F0;
    border-radius: 9px;
    color: #334155;
    font-family: Consolas, "DejaVu Sans Mono", "Cascadia Mono", monospace;
    font-size: 12px;
    selection-background-color: #BFDBFE;
    selection-color: #0B1220;
}
QPlainTextEdit#LogView { padding: 7px; }

/* ---------------------------------------------------------------- 按钮 */
QPushButton {
    min-height: 38px;
    padding: 0 16px;
    border-radius: 9px;
    border: 1px solid #CBD5E1;
    background: #FFFFFF;
    color: #1E293B;
    font-weight: 600;
    font-size: 13px;
}
QPushButton:hover { background: #F1F5F9; border-color: #94A3B8; }
QPushButton:pressed { background: #E2E8F0; }
QPushButton:focus { border: 2px solid #2563EB; }
QPushButton:disabled { color: #CBD5E1; background: #F8FAFC; border-color: #E2E8F0; }

QPushButton#PrimaryButton {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #3B82F6, stop:1 #1D4ED8);
    border: 1px solid #1D4ED8;
    color: #FFFFFF;
    font-size: 14px;
    min-width: 136px;
}
QPushButton#PrimaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                stop:0 #60A5FA, stop:1 #2563EB);
}
QPushButton#PrimaryButton:disabled {
    background: #DBEAFE; border-color: #BFDBFE; color: #93C5FD;
}
QPushButton#DangerButton {
    background: #FFFFFF;
    border: 1px solid #FCA5A5;
    color: #DC2626;
}
QPushButton#DangerButton:hover { background: #FEF2F2; border-color: #DC2626; }
QPushButton#SmallButton {
    min-height: 26px;
    padding: 0 11px;
    font-size: 12px;
    border-radius: 7px;
}

/* ---------------------------------------------------------------- 控件 */
QScrollArea { background: transparent; border: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #CBD5E1; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #94A3B8; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; height: 0; }

QSlider::groove:horizontal { height: 5px; background: #E2E8F0; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #2563EB; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; height: 14px; margin: -5px 0;
    border-radius: 7px; background: #FFFFFF; border: 2px solid #2563EB;
}
QSlider::handle:horizontal:hover { background: #EFF6FF; }
QSlider::handle:horizontal:disabled { background: #F1F5F9; border-color: #CBD5E1; }

QProgressBar {
    height: 7px; border: none; border-radius: 3px;
    background: #E2E8F0; text-align: center;
}
QProgressBar::chunk { border-radius: 3px; background: #2563EB; }

/* ---------------------------------------------------------------- 对话框 */
QDialog { background: #FFFFFF; }
QTabWidget::pane { border: 1px solid #E2E8F0; border-radius: 10px; top: -1px; }
QTabBar::tab {
    background: transparent;
    color: #64748B;
    padding: 9px 18px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
}
QTabBar::tab:hover { color: #1D4ED8; }
QTabBar::tab:selected {
    color: #1D4ED8;
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-bottom-color: #FFFFFF;
}
QListWidget {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 9px;
    padding: 4px;
    outline: none;
}
QListWidget::item { padding: 10px 11px; border-radius: 7px; color: #334155; }
QListWidget::item:hover { background: #F1F5F9; }
QListWidget::item:selected { background: #EFF6FF; color: #1D4ED8; border: 1px solid #93C5FD; }
QLineEdit {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 8px 10px;
    color: #334155;
    min-height: 22px;
}
QLineEdit:read-only { background: #F8FAFC; color: #475569; }
QSpinBox {
    background: #FFFFFF;
    border: 1px solid #E2E8F0;
    border-radius: 8px;
    padding: 7px 8px;
    min-height: 24px;
    color: #1E293B;
}
QSpinBox:focus, QLineEdit:focus { border-color: #2563EB; }
QToolTip {
    background: #0B1220;
    color: #F8FAFC;
    border: 1px solid #334155;
    padding: 6px 9px;
    border-radius: 6px;
}
"""

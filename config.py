"""
=============================================================================
 配置文件 —— 你可以自由修改本文件中的数值来定制软件行为
=============================================================================
 修改后保存文件，重新启动软件即可生效。
 颜色值使用 CSS 十六进制格式：#RRGGBB
 所有带"默认"字样的值，只在首次运行或重置设置后生效。
=============================================================================
"""

import os
from PyQt5.QtCore import QSettings

# ============================================================================
# 第一部分：路径与目录
# ============================================================================

# BASE_DIR = 软件所在的文件夹（自动获取，无需修改）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# DATA_DIR = 所有数据存放的文件夹
DATA_DIR = os.path.join(BASE_DIR, "data")

# IMAGE_DIR = 题目图片存放的文件夹
IMAGE_DIR = os.path.join(DATA_DIR, "images")

# DB_PATH = 数据库文件路径
DB_PATH = os.path.join(DATA_DIR, "question_bank.db")

# 自动创建必要的文件夹
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

# ============================================================================
# 第二部分：窗口与外观
# ============================================================================

# 窗口默认宽度（像素），首次启动时使用
WINDOW_WIDTH = 1200

# 窗口默认高度（像素），首次启动时使用
WINDOW_HEIGHT = 750

# 窗口标题栏显示的文字
WINDOW_TITLE = "我的题库"

# ---------------------------------------------------------------------------
# 配色方案 —— 修改这些值可以改变整个软件的色调
# ---------------------------------------------------------------------------

PRIMARY_COLOR = "#4A90D9"     # 主色调（按钮、选中态、强调元素）
PRIMARY_HOVER = "#357ABD"     # 鼠标悬停在主色按钮上时的颜色
BG_COLOR = "#ECECEC"          # 页面背景色
SIDEBAR_BG = "#BBDFE6"        # 左侧导航栏背景色
CARD_BG = "#FFFFFF"           # 卡片和输入框背景色
TEXT_COLOR = "#333333"        # 正文文字颜色
SUB_TEXT_COLOR = "#888888"    # 次要文字颜色（提示、说明）
CORRECT_COLOR = "#52C41A"     # "正确"按钮颜色（绿色）
WRONG_COLOR = "#FF4D4F"       # "错误"按钮颜色（红色）


# ============================================================================
# 第三部分：持久化设置（由软件自动管理，一般不需要手动修改）
# 数据存储在 Windows 注册表：HKEY_CURRENT_USER\Software\MyQB\QuestionBank
# ============================================================================

class AppSettings:
    """
    所有用户可调的设置项。
    在软件中打开"设置"页面即可修改，修改后立即生效并自动保存。
    """

    # 字号缩放范围（百分比）
    MIN_SCALE = 80   # 最小缩小到 80%
    MAX_SCALE = 200  # 最大放大到 200%

    def __init__(self):
        # QSettings 读写 Windows 注册表
        self._s = QSettings("MyQB", "QuestionBank")

    # ------------------------------------------------------------------
    # 字体缩放 —— 控制全软件的字号大小
    # 可在设置页面拖动滑块，或按住 Ctrl + 滚动鼠标滚轮
    # ------------------------------------------------------------------

    @property
    def font_scale(self):
        """当前字号缩放百分比，默认 100（即 100%）"""
        return int(self._s.value("font_scale", 100))

    def set_font_scale(self, value):
        """设置字号缩放百分比（自动限制在 MIN_SCALE ~ MAX_SCALE 之间）"""
        v = max(self.MIN_SCALE, min(self.MAX_SCALE, int(value)))
        self._s.setValue("font_scale", v)

    def adjust_font_scale(self, delta):
        """在现有基础上增减字号（Ctrl+滚轮时调用，delta=5 或 -5）"""
        self.set_font_scale(self.font_scale + delta)

    # ------------------------------------------------------------------
    # 默认抽题数量 —— 进入"组卷考试"页面时的默认值
    # ------------------------------------------------------------------

    @property
    def default_exam_count(self):
        """默认抽题数，默认 10 题"""
        return int(self._s.value("default_exam_count", 10))

    def set_default_exam_count(self, value):
        self._s.setValue("default_exam_count", int(value))

    # ------------------------------------------------------------------
    # 输入框行数 —— 录题页面题目/答案/备注输入框的显示高度
    # ------------------------------------------------------------------

    @property
    def input_lines(self):
        """输入框显示的行数，默认 7 行，范围 3~20"""
        return int(self._s.value("input_lines", 7))

    def set_input_lines(self, value):
        self._s.setValue("input_lines", max(3, min(20, int(value))))

    # ------------------------------------------------------------------
    # 题库图片显示模式 —— "thumb"=缩略图 / "full"=原图
    # ------------------------------------------------------------------

    @property
    def image_display_mode(self):
        """图片显示模式："thumb"（缩略图）或 "full"（原图）"""
        return self._s.value("image_display_mode", "thumb")

    def set_image_display_mode(self, value):
        self._s.setValue("image_display_mode", value)

    @property
    def image_quality(self):
        """图片压缩比例：35, 50, 75, 100（默认50%）"""
        return int(self._s.value("image_quality", 50))

    def set_image_quality(self, value):
        self._s.setValue("image_quality", int(value))

    # ------------------------------------------------------------------
    # 字号计算 —— 根据缩放百分比算出各类文字的实际像素大小
    #
    # 公式：实际字号 = 基础字号 × 缩放百分比 ÷ 100
    #
    # 修改下面的"基础字号"（如 14, 22, 15 等）可以调整各类文字的
    # 默认大小。例如想把正文字号改为 16px，就把 14 改成 16。
    # ------------------------------------------------------------------

    def get_font_sizes(self):
        """
        返回 7 种字号的元组：(正文, 标题, 导航, 设置标题, 侧边栏, 小字, 大字按钮)

        100%（默认）时的字号：
          base=14px     正文和输入框
          title=22px    页面标题（如"录入题目"）
          nav=15px      导航按钮（实际使用硬编码，此值仅作参考）
          section=18px  设置页卡片标题
          sidebar=28px  侧边栏文字（实际使用硬编码，此值仅作参考）
          small=12px    小字（标签、提示）
          big=16px      大字按钮（正确/错误）
        """
        s = self.font_scale
        return (
            max(9, round(14 * s / 100)),    # base — 正文基础字号（默认 14px）
            max(14, round(22 * s / 100)),   # title — 页面标题字号（默认 22px）
            max(10, round(15 * s / 100)),   # nav — 导航字号（默认 15px）
            max(12, round(18 * s / 100)),   # section — 设置卡片标题（默认 18px）
            max(16, round(28 * s / 100)),   # sidebar — 侧边栏字号（默认 28px）
            max(8, round(12 * s / 100)),    # small — 小号文字（默认 12px）
            max(11, round(16 * s / 100)),   # big — 大号按钮（默认 16px）
        )

    # ------------------------------------------------------------------
    # 表格列宽记忆 —— 自动保存和恢复表格各列的宽度
    # ------------------------------------------------------------------

    def save_table_columns(self, name, widths):
        """保存表格列宽（name="question_list" 或 "wrong_collection"）"""
        self._s.setValue(f"table_{name}_cols", ",".join(str(w) for w in widths))

    def load_table_columns(self, name):
        """读取上次保存的表格列宽，没有保存过则返回 None"""
        val = self._s.value(f"table_{name}_cols", "")
        if val:
            return [int(x) for x in str(val).split(",")]
        return None

    # ------------------------------------------------------------------
    # 窗口状态记忆 —— 关闭软件时保存窗口大小和位置，下次打开时恢复
    # ------------------------------------------------------------------

    def save_window_geometry(self, geometry_bytes):
        """保存窗口位置和大小（关闭软件时自动调用）"""
        self._s.setValue("window_geometry", geometry_bytes)

    def load_window_geometry(self):
        """读取上次的窗口位置和大小（启动软件时自动调用）"""
        return self._s.value("window_geometry", None)

    # ------------------------------------------------------------------
    # 样式表加载 —— 将 ui/styles.qss 中的字号占位符替换为实际数值
    # 占位符对照：
    #   {font_base}    → 正文字号
    #   {font_title}   → 标题字号
    #   {font_nav}     → 导航字号
    #   {font_section} → 设置标题字号
    #   {font_sidebar} → 侧边栏字号
    #   {font_small}   → 小字号
    #   {font_big}     → 大按钮字号
    # ------------------------------------------------------------------

    def build_stylesheet(self, qss_path):
        """读取 QSS 样式文件，把字号和颜色的占位符替换为实际值"""
        base, title, nav, section, sidebar, small, big = self.get_font_sizes()
        with open(qss_path, "r", encoding="utf-8") as f:
            qss = f.read()
        return self._replace_placeholders(qss)

    def build_dynamic_style(self, style_string):
        """替换单个样式字符串中的字号/颜色占位符（用于硬编码 setStyleSheet 调用）"""
        return self._replace_placeholders(style_string)

    def _replace_placeholders(self, text):
        """替换字号和颜色占位符为实际数值"""
        base, title, nav, section, sidebar, small, big = self.get_font_sizes()
        return (text
            .replace("{font_base}", str(base))
            .replace("{font_title}", str(title))
            .replace("{font_nav}", str(nav))
            .replace("{font_section}", str(section))
            .replace("{font_sidebar}", str(sidebar))
            .replace("{font_small}", str(small))
            .replace("{font_big}", str(big))
            .replace("{color_bg}", BG_COLOR)
            .replace("{color_sidebar}", SIDEBAR_BG)
            .replace("{color_card}", CARD_BG)
            .replace("{color_primary}", PRIMARY_COLOR)
            .replace("{color_primary_hover}", PRIMARY_HOVER)
            .replace("{color_text}", TEXT_COLOR)
            .replace("{color_subtext}", SUB_TEXT_COLOR)
            .replace("{color_correct}", CORRECT_COLOR)
            .replace("{color_wrong}", WRONG_COLOR))

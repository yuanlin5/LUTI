"""
=============================================================================
 主窗口 —— Fluent 侧边栏导航 + 多页面内容区
=============================================================================

本文件是软件 UI 的核心骨架，负责：
  1. 创建主窗口（基于 qfluentwidgets 的 MSFluentWindow）
  2. 左侧侧边栏导航（4 个功能页面 + 底部版本标签）
  3. 右侧内容区切换（QStackedWidget 管理 4 个面板）
  4. Ctrl+滚轮 全局字体缩放
  5. 面板生命周期管理（on_shown 自动触发数据刷新）
=============================================================================
"""

# ============================================================================
# 第一部分：导入依赖
# ============================================================================

# --- PyQt5 核心组件 ---
from PyQt5.QtWidgets import (                     # Qt 控件模块
    QWidget,                                      # 所有控件的基类
    QHBoxLayout,                                  # 水平布局
    QStackedWidget,                               # 堆叠页面容器（一次只显示一个子页面）
    QLabel,                                       # 标签控件
    QMessageBox,                                  # 消息弹窗（信息/警告/错误）
    QApplication,                                 # 应用程序实例（管理事件循环）
)
from PyQt5.QtCore import Qt, QEvent, QRectF, QRect  # 核心模块：枚举/事件/矩形
#   Qt        = 键盘修饰键（Ctrl/Shift 等）、对齐方式等枚举
#   QEvent    = 事件类型（滚轮/按键等）
#   QRectF    = 浮点精度矩形（用于图标绘制定位）
#   QRect     = 整数精度矩形（用于文字绘制定位）
from PyQt5.QtGui import QIcon                     # 图标类（设置窗口图标等）

# --- qfluentwidgets 组件（Fluent Design 风格控件库）---
from qfluentwidgets import (
    MSFluentWindow,                               # Fluent 风格主窗口基类（= 侧边栏 + 堆叠页面）
    NavigationInterface,                          # 导航栏接口（提供 addItem/setCurrentItem 等方法）
    NavigationItemPosition,                       # 导航项位置枚举：TOP=顶部 / BOTTOM=底部
    FluentIcon,                                   # Fluent 内置图标枚举（HOME/EDIT/LIBRARY 等）
    setTheme,                                     # 设置主题函数
    Theme,                                        # 主题枚举：AUTO=自动 / LIGHT=亮色 / DARK=暗色
    InfoBar,                                      # 信息条（右上角弹出通知）
    InfoBarPosition,                              # 信息条位置枚举
    PushButton,                                   # Fluent 风格按钮
    FluentIconBase,                               # Fluent 图标基类（用于 isinstance 类型判断）
    drawIcon,                                     # 图标绘制函数（将 QIcon/FluentIcon 渲染到指定矩形）
)
from qfluentwidgets.common.color import autoFallbackThemeColor  # 自动获取亮/暗主题对应颜色
from qfluentwidgets.common.style_sheet import isDarkTheme       # 判断当前是否为暗色主题

# --- Python 标准库 ---
import json                                      # JSON 读写（读取 icon_config.json）
import os as _os                                 # 文件路径操作（用 _os 避免与模块名 os 冲突）

# --- 项目内部模块 ---
from config import (                             # 全局配置
    WINDOW_WIDTH,                                # 默认窗口宽度（1200px）
    WINDOW_HEIGHT,                               # 默认窗口高度（750px）
    WINDOW_TITLE,                                # 窗口标题文字
    AppSettings,                                 # 用户设置管理类（字号/行数/图片模式等持久化存储）
)

# --- 四个功能面板（每个面板是一个独立页面）---
from ui.add_question import AddQuestionPanel     # "录入题目" 面板
from ui.question_list import QuestionListPanel    # "题库管理" 面板
from ui.exam_panel import ExamPanel              # "组卷考试" 面板
from ui.settings_panel import SettingsPanel      # "设置" 面板


# ============================================================================
# 第二部分：侧边栏导航按钮增强（Monkey-Patch）
# ============================================================================

def _patch_nav_button(btn):
    """
    对单个导航按钮进行运行时增强（Monkey-Patch）：
      - _drawIcon  : 图标绘制矩形从 20×20 扩大为 28×28
      - _drawText  : 文字绘制位置从 y=32 下移至 y=38（避免与放大图标重叠）

    调用时机：_fix_sidebar() 方法中遍历所有 NavigationBarPushButton 后逐个调用

    参数:
        btn (NavigationBarPushButton): qfluentwidgets 导航栏按钮实例
    """

    # ================================================================
    # Patch 1：_drawIcon —— 放大图标绘制区域
    # ================================================================
    orig_draw_icon = btn._drawIcon                # 保存原始 _drawIcon 方法的引用

    def patched_draw_icon(painter):
        """
        替换后的 _drawIcon 方法。
        与原始实现的区别仅为：绘制矩形从 QRectF(22,13,20,20) → QRectF(16,5,28,28)

        参数:
            painter (QPainter): Qt 绘图上下文
        """
        # 若按钮被按下 或 鼠标不在按钮上，且按钮未选中 → 半透明显示（60%）
        if (btn.isPressed or not btn.isEnter) and \
           not (btn.isSelected or btn.isAboutSelected):
            painter.setOpacity(0.6)               # 设置画笔透明度为 60%
        # 若按钮被禁用 → 更透明（40%）
        if not btn.isEnabled():
            painter.setOpacity(0.4)               # 设置画笔透明度为 40%

        # 根据侧边栏展开/折叠状态决定图标矩形
        if btn._isSelectedTextVisible:            # 侧边栏展开时 → 文字可见
            rect = QRectF(16, 5, 28, 28)          # ┌── 可调整 ──┐
                                                  # (x=16, y=5, 宽=28, 高=28)
                                                  # x=16: 图标离左边缘 16px
                                                  # y=5:  图标离顶边缘 5px（贴顶）
                                                  # 宽28: 图标宽度（默认 20，放大约 1.4 倍）
                                                  # 高28: 图标高度
        else:                                     # 侧边栏折叠时 → 仅图标可见
            rect = QRectF(16, 5 + btn.iconAni.offset, 28, 28)
                                                  # iconAni.offset = 展开动画的垂直偏移量

        # 确定要绘制的图标：选中态优先使用 _selectedIcon，否则用 _icon
        selected = btn._selectedIcon or btn._icon

        # 分三种情况绘制图标
        if isinstance(selected, FluentIconBase) and \
           (btn.isSelected or btn.isAboutSelected):
            # 情况1：选中/即将选中 + Fluent 图标 → 用主题颜色填充 SVG
            color = autoFallbackThemeColor(        # 自动适配亮/暗主题颜色
                btn.lightSelectedColor,            # 亮色主题下选中态颜色
                btn.darkSelectedColor)             # 暗色主题下选中态颜色
            selected.render(painter, rect, fill=color.name())  # 渲染 SVG 到指定矩形

        elif btn.isSelected or btn.isAboutSelected:
            # 情况2：选中 + 非 Fluent 图标（QIcon 等）→ 通用绘制
            drawIcon(selected, painter, rect)

        else:
            # 情况3：未选中 → 用默认图标绘制
            drawIcon(btn._icon, painter, rect)

    btn._drawIcon = patched_draw_icon             # 替换原始方法

    # ================================================================
    # Patch 2：_drawText —— 下移文字绘制位置
    # ================================================================
    def patched_draw_text(painter):
        """
        替换后的 _drawText 方法。
        与原始实现的区别仅为：文字矩形从 QRect(0,32,...) → QRect(0,38,...)
        注：不能直接调用 orig_draw_text 再偏移，因为 painter 坐标会累积，
        所以完整重写了绘图逻辑。

        参数:
            painter (QPainter): Qt 绘图上下文
        """
        # 若当前选中 且 侧边栏折叠（文字不可见）→ 不绘制文字
        if btn.isSelected and not btn._isSelectedTextVisible:
            return

        # 根据选中状态选择文字颜色
        if btn.isSelected or btn.isAboutSelected:
            # 选中/即将选中 → 使用主题选中色
            painter.setPen(autoFallbackThemeColor(
                btn.lightSelectedColor,            # 亮色主题选中文字颜色
                btn.darkSelectedColor))            # 暗色主题选中文字颜色
        else:
            # 未选中 → 亮色主题用黑色，暗色主题用白色
            painter.setPen(Qt.white if isDarkTheme() else Qt.black)

        # 应用按钮自身的字体设置
        painter.setFont(btn.font())

        # ┌── 可调整 ──┐
        rect = QRect(0, 60, 60, 22)       # 文字矩形
                                                   # x=0:  离左边缘 0px（整行宽度）
                                                   # y=60: 离顶边缘 60px（原始为 32）
                                                   # 宽=60: 文字行宽（原始为 60）
                                                   # 高=22: 文字行高（原始为 26）

        # 在矩形内居中绘制按钮文字
        painter.drawText(rect, Qt.AlignCenter, btn.text())

    btn._drawText = patched_draw_text             # 替换原始方法


# ============================================================================
# 第三部分：主窗口类
# ============================================================================

class MainWindow(MSFluentWindow):
    """
    软件主窗口。
    继承自 qfluentwidgets.MSFluentWindow（= NavigationBar + QStackedWidget 组合）

    结构示意：
    ┌──────────┬─────────────────────────────┐
    │ 侧边栏   │  内容区（QStackedWidget）    │
    │          │                             │
    │ 录入题目 │  ← 四个功能面板按需切换 →    │
    │ 题库管理 │                             │
    │ 组卷考试 │                             │
    │          │                             │
    │   设置   │                             │
    └──────────┴─────────────────────────────┘
    """

    # ════════════════════════════════════════════════════════════════
    # switchTo —— 页面切换钩子（覆盖父类方法）
    # ════════════════════════════════════════════════════════════════
    def switchTo(self, interface):
        """
        切换当前显示的页面，并在切换后自动触发新页面的 on_shown() 回调。

        覆盖 MSFluentWindow.switchTo 以支持：
          1. 兼容字符串 routeKey（侧边栏点击时传入的是路由键，不是 QWidget）
          2. 自动调用目标面板的 on_shown() 方法（刷新数据）

        参数:
            interface (QWidget | str): 目标面板对象 或 路由键字符串
        """
        super().switchTo(interface)               # 调用父类方法完成实际页面切换

        target = interface                        # 记录目标面板（初始值 = 传入参数）
        if isinstance(interface, str):            # 如果传入的是字符串（侧边栏点击走这条路）
            for i in range(self.stackedWidget.count()):  # 遍历堆叠容器中的所有子页面
                w = self.stackedWidget.widget(i)  # 获取第 i 个子页面控件
                if w.objectName() == interface:   # 子页面的 objectName 与路由键匹配？
                    target = w                    # 找到！记录实际控件引用
                    break                         # 停止遍历

        try:                                      # 防御性 try-except（防止面板未就绪等边界情况）
            if hasattr(target, 'on_shown') and not isinstance(target, str):
                target.on_shown()                 # 触发面板的 on_shown 回调（刷新数据）
        except Exception:
            pass                                  # 静默忽略所有异常

    # ════════════════════════════════════════════════════════════════
    # __init__ —— 构造函数
    # ════════════════════════════════════════════════════════════════
    def __init__(self):
        """创建主窗口实例，完成整个 UI 的初始化流程"""
        super().__init__()                        # 调用父类 MSFluentWindow 构造

        # ---- 基础属性 ----
        self.settings = AppSettings()             # 创建用户设置管理器实例（读写注册表）

        # ---- 窗口属性 ----
        self.setWindowTitle(WINDOW_TITLE)         # 设置标题栏文字
        self.setMinimumSize(900, 600)             # 限制窗口最小尺寸（防止面板被挤压变形）
        setTheme(Theme.AUTO)                      # 设置主题为"自动"（白天亮色 / 夜晚暗色）

        # ---- 窗口尺寸恢复 ----
        geo = self.settings.load_window_geometry() # 从注册表读取上次保存的窗口位置和尺寸
        if geo:                                    # 如果之前保存过？
            self.restoreGeometry(geo)              # 恢复为上次关闭时的窗口状态
        else:                                      # 首次启动？
            self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)  # 使用 config.py 中定义的默认尺寸

        # ---- 初始化流程 ----
        self._load_app_icon()                     # 步骤1：加载应用图标（taskbar 和标题栏显示）
        self._setup_panels()                      # 步骤2：创建 4 个功能面板
        self._setup_navigation()                  # 步骤3：配置侧边栏导航项
        self._connect_signals()                   # 步骤4：连接面板间的信号与槽

        # ---- 主题与样式 ----
        self._apply_stylesheet()                  # 步骤5：加载 QSS 样式表（字体/颜色）

        # ---- 侧边栏微调 ----
        self._fix_sidebar()                       # 步骤6：加宽侧边栏 + 放大图标 + 调整文字位置

        # ---- 默认页面 ----
        self.switchTo(self.add_question_panel)    # 步骤7：默认显示"录入题目"页面
        # switchTo 会自动调用 add_question_panel.on_shown()

        # ---- 全局事件过滤器 ----
        QApplication.instance().installEventFilter(self)  # 安装事件过滤器，捕获 Ctrl+滚轮

    # ════════════════════════════════════════════════════════════════
    # _setup_panels —— 创建并注册 4 个功能面板
    # ════════════════════════════════════════════════════════════════
    def _setup_panels(self):
        """创建 4 个功能面板实例，并通过 addSubInterface 注册到主窗口"""
        # 创建面板实例
        self.add_question_panel = AddQuestionPanel()     # 录入题目面板
        self.question_list_panel = QuestionListPanel()    # 题库管理面板
        self.exam_panel = ExamPanel()                    # 组卷考试面板
        self.settings_panel = SettingsPanel()            # 设置面板

        # ---- 注册面板到 MSFluentWindow ----
        # addSubInterface 同时做两件事：
        #   1. 将面板加入 QStackedWidget（内容区的页面堆叠容器）
        #   2. 在侧边栏添加一个导航按钮
        # 参数：(routeKey 路由键, icon 图标, text 显示文字, position 位置)
        panel_configs = [
            # ┌───路由键(页面ID)───┬───面板实例───┬───侧边栏图标───┬───位置───┐
            ("录入题目", self.add_question_panel, FluentIcon.EDIT,     # 顶部
             NavigationItemPosition.TOP),
            ("题库管理", self.question_list_panel, FluentIcon.LIBRARY, # 顶部
             NavigationItemPosition.TOP),
            ("组卷考试", self.exam_panel, FluentIcon.EDUCATION,       # 顶部
             NavigationItemPosition.TOP),
            ("设置",     self.settings_panel, FluentIcon.SETTING,     # 底部（靠底）
             NavigationItemPosition.BOTTOM),
        ]

        for route, panel, icon, pos in panel_configs:  # 遍历配置列表
            panel.setObjectName(route)                 # 设置控件的 objectName（等于路由键）
            # 路由键的用途：
            #   1. switchTo("录入题目") 可通过字符串查找目标面板
            #   2. 导航按钮点击时，传给 switchTo 的就是这个字符串
            self.addSubInterface(panel, icon, route, position=pos)
            #                      面板   图标  文字   位置

    # ════════════════════════════════════════════════════════════════
    # _setup_navigation —— 侧边栏额外配置
    # ════════════════════════════════════════════════════════════════
    def _setup_navigation(self):
        """设置侧边栏底部版本标签等额外的导航栏元素"""
        nav = self.navigationInterface              # 获取对侧边栏的引用

        # ---- 底部版本标签（显示作者和版本号）----
        ver_btn = PushButton("v1.0 — 王若水")       # 使用 PushButton 作为标签（纯展示用）
        ver_btn.setFlat(True)                        # 设为扁平样式（无边框背景）
        ver_btn.setStyleSheet("color: #888; font-size: 12px;")  # 灰色小字，与导航按钮区分
        ver_btn.clicked.connect(self._show_version_info)       # 点击→弹出"关于"对话框
        nav.addWidget("versionLabel", ver_btn,       # 将按钮添加到导航栏
                       position=NavigationItemPosition.BOTTOM)  # 固定在底部

    # ════════════════════════════════════════════════════════════════
    # _fix_sidebar —— 侧边栏微调
    # ════════════════════════════════════════════════════════════════
    def _fix_sidebar(self):
        """
        对侧边栏进行三项微调：
          1. 增加宽度（180px，容纳中文 + 放大图标）
          2. 放大所有导航按钮的图标（28×28）
          3. 下移导航按钮的文字（避免与图标重叠）
        """
        nav = self.navigationInterface              # 获取侧边栏引用
        nav.setMinimumWidth(180)                    # ┌── 可调整 ──┐
                                                   # 设置侧边栏最小宽度为 180 像素
                                                   # 足够容纳：图标宽~28 + 4个中文字~56 + 边距

        # 找到侧边栏中的所有导航按钮
        from qfluentwidgets.components.navigation.navigation_bar import \
            NavigationBarPushButton                # 导航按钮的类（不是公开 API，但运行时可用）
        for btn in nav.findChildren(NavigationBarPushButton):  # 递归查找所有按钮子控件
            try:
                _patch_nav_button(btn)             # 对每个按钮进行 monkey-patch（放大图标+下移文字）
            except Exception:
                pass                               # 某个按钮打补丁失败不影响其他按钮

    # ════════════════════════════════════════════════════════════════
    # _setup_menu —— 菜单栏（未使用）
    # ════════════════════════════════════════════════════════════════
    def _setup_menu(self):
        """MSFluentWindow 不支持 QMenuBar，用途由侧边栏导航替代"""
        pass                                       # 预留接口，暂无实现

    # ════════════════════════════════════════════════════════════════
    # _connect_signals —— 信号/槽连接
    # ════════════════════════════════════════════════════════════════
    def _connect_signals(self):
        """连接面板之间的通信信号（实现跨面板联动）"""
        # 题库管理面板 → 编辑按钮被点击 → 跳转到录入面板并加载该题目
        self.question_list_panel.edit_requested.connect(self._on_edit_question)

        # 设置面板 → 字体大小改变（滑块/滚轮） → 全局更新字体
        self.settings_panel.font_changed.connect(self._on_font_changed)

        # 设置面板 → 输入框行数改变 → 更新录入面板的编辑框高度
        self.settings_panel.input_lines_changed.connect(self._on_input_lines_changed)

        # 设置面板 → 图片显示模式改变 → 刷新题库面板的表格
        self.settings_panel.image_mode_changed.connect(self._on_image_mode_changed)

        # 设置面板 → 默认抽题数量改变 → 更新考试面板的默认值
        self.settings_panel.exam_default_changed.connect(self._on_exam_default_changed)

    # ════════════════════════════════════════════════════════════════
    # 导航回调方法
    # ════════════════════════════════════════════════════════════════

    def _nav_to(self, idx):
        """
        按索引跳转到指定面板（0=录入题目, 1=题库管理, 2=组卷考试）

        参数:
            idx (int): 面板索引，0~2
        """
        route_keys = ["录入题目", "题库管理", "组卷考试"]  # 三个面板的路由键
        panels = [self.add_question_panel,                # 对应的面板实例
                  self.question_list_panel,
                  self.exam_panel]
        if 0 <= idx < len(panels):                        # 索引合法性检查
            self.navigationInterface.setCurrentItem(route_keys[idx])  # 高亮侧边栏按钮
            self.switchTo(panels[idx])                    # 切换内容区页面（自动调用 on_shown）

    def _show_settings(self):
        """跳转到设置面板"""
        self.navigationInterface.setCurrentItem("设置")   # 高亮"设置"导航按钮
        self.switchTo(self.settings_panel)               # 切换页面（自动调用 on_shown）

    def _on_edit_question(self, qid):
        """
        响应题库管理面板的"编辑"按钮 → 跳到录入面板并加载题目数据

        参数:
            qid (int): 要编辑的题目 ID
        """
        self.navigationInterface.setCurrentItem("录入题目")  # 高亮"录入题目"导航按钮
        self.switchTo(self.add_question_panel)               # 切换到录入面板
        # switchTo 已自动调用了 on_shown()（清空表单）
        self.add_question_panel.load_question(qid)           # 加载题目数据到表单

    # ════════════════════════════════════════════════════════════════
    # _apply_stylesheet —— 全局样式表加载
    # ════════════════════════════════════════════════════════════════
    def _apply_stylesheet(self):
        """
        从 ui/styles.qss 加载全局样式表，替换其中的字号和颜色占位符后应用。

        占位符说明（在 styles.qss 中使用）：
          {font_base}   → 正文字号（默认 14px）
          {font_title}  → 标题字号（默认 22px）
          {font_big}    → 大按钮字号（默认 16px）
          {color_bg}    → 背景色 (#ECECEC)
          ... 等等（由 AppSettings.build_stylesheet 统一替换）
        """
        try:
            # 拼接 styles.qss 文件的绝对路径
            # __file__ = ui/main_window.py  →  os.path.dirname = ui/
            qss_path = _os.path.join(_os.path.dirname(
                _os.path.abspath(__file__)), "styles.qss")
            if _os.path.exists(qss_path):             # 文件存在才继续
                qss = self.settings.build_stylesheet(qss_path)  # 读取 QSS 并替换占位符
                QApplication.instance().setStyleSheet(qss)      # 全局应用样式表
        except Exception:
            pass                                      # 加载失败不阻塞启动

    # ════════════════════════════════════════════════════════════════
    # 信号处理回调
    # ════════════════════════════════════════════════════════════════

    def _on_font_changed(self):
        """字体缩放比例改变时被调用（滑块拖动 或 Ctrl+滚轮）"""
        self._apply_stylesheet()                      # 1. 重建并重新应用全局样式表
        self.add_question_panel.update_input_heights()  # 2. 更新录入面板编辑框高度
        self.add_question_panel.update_dynamic_styles() # 3. 更新录入面板内联样式
        self.exam_panel.update_dynamic_styles()         # 4. 更新考试面板内联样式
        self.question_list_panel.update_dynamic_styles()# 5. 刷新题库面板表格（字号变化后重绘）

    def _on_input_lines_changed(self):
        """输入框行数设置改变时被调用"""
        self.add_question_panel.update_input_heights()  # 更新录入面板的编辑框行高

    def _on_image_mode_changed(self):
        """图片显示模式改变时被调用（缩略图 ↔ 原图）"""
        self.question_list_panel._do_search()           # 刷新题库面板（重新显示图片）

    def _on_exam_default_changed(self, count):
        """考试默认抽题数改变时被调用"""
        self.exam_panel.set_default_count(count)        # 更新考试面板的默认数量

    def _switch_and_export(self):
        """导出题库的快捷方法（跳转到题库面板并触发导出）"""
        self.navigationInterface.setCurrentItem("题库管理")  # 高亮导航按钮
        self.switchTo(self.question_list_panel)               # 切换面板（自动 on_shown）
        self.question_list_panel._export_questions()          # 触发导出流程

    # ════════════════════════════════════════════════════════════════
    # _load_app_icon —— 加载自定义应用图标
    # ════════════════════════════════════════════════════════════════
    def _load_app_icon(self):
        """
        从 resources/icon_config.json 读取图标配置，加载自定义应用图标。

        配置文件格式：
          {"app_icon": "main_icon.png"}
          → 表示使用 resources/icons/main_icon.png

        留空或文件不存在 → 使用默认图标
        """
        try:
            # 构建 icon_config.json 的路径
            # __file__ = ui/main_window.py
            # os.path.dirname(__file__) = ui/
            # os.path.dirname(ui/) = 项目根目录/
            config_path = _os.path.join(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__))), "resources", "icon_config.json")
            if _os.path.exists(config_path):          # 配置文件存在？
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)                # 读取 JSON 配置
                icon_name = cfg.get("app_icon", "")   # 获取 app_icon 键对应的文件名
                if icon_name:                         # 有配置图标文件名？
                    # 构建图标文件的路径：resources/icons/<文件名>
                    icon_path = _os.path.join(_os.path.dirname(config_path),
                                              "icons", icon_name)
                    if _os.path.exists(icon_path):    # 图标文件存在？
                        self.setWindowIcon(QIcon(icon_path))  # 设置窗口图标
        except Exception:
            pass                                      # 加载失败不影响启动

    # ════════════════════════════════════════════════════════════════
    # _show_version_info —— 关于对话框
    # ════════════════════════════════════════════════════════════════
    def _show_version_info(self):
        """点击版本标签时弹窗显示软件信息"""
        QMessageBox.about(self, "关于",              # about() = 无图标信息弹窗
            "<h3>我的题库 v1.0</h3>"                  # HTML 格式标题
            "<p>一款轻量级桌面题库管理软件</p>"        # 描述
            "<p>作者：<b>王若水</b></p>"              # 作者（加粗）
        )

    # ════════════════════════════════════════════════════════════════
    # closeEvent —— 窗口关闭事件
    # ════════════════════════════════════════════════════════════════
    def closeEvent(self, event):
        """
        窗口即将关闭时被系统调用。保存当前窗口位置和大小到注册表。

        参数:
            event (QCloseEvent): Qt 关闭事件对象
        """
        self.settings.save_window_geometry(self.saveGeometry())  # 保存窗口几何信息
        super().closeEvent(event)                     # 调用父类关闭处理

    # ════════════════════════════════════════════════════════════════
    # eventFilter —— 全局事件过滤器
    # ════════════════════════════════════════════════════════════════
    def eventFilter(self, obj, event):
        """
        拦截全局事件。主要用途：捕获 Ctrl+鼠标滚轮 进行字体缩放。

        参数:
            obj (QObject): 接收到事件的控件
            event (QEvent): 事件详情

        返回:
            bool: True=事件已处理并吃掉 / False=继续传递给目标控件
        """
        if event.type() == QEvent.Wheel:              # 是否鼠标滚轮事件？
            if event.modifiers() & Qt.ControlModifier: # 是否同时按住了 Ctrl 键？
                delta = event.angleDelta().y()        # 获取滚轮滚动距离（正=向上滚，负=向下滚）
                step = 5 if delta > 0 else -5         # 向上→放大 5%，向下→缩小 5%
                self.settings.adjust_font_scale(step) # 调整字号缩放值（自动限制 80%~200%）
                self._on_font_changed()               # 触发全局字体刷新
                return True                           # 返回 True 表示"事件已处理，不再传递"
        return super().eventFilter(obj, event)        # 非 Ctrl+滚轮 → 走默认处理

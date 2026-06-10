"""
=============================================================================
 主窗口 —— Fluent 侧边栏导航 + 多页面内容区
=============================================================================
"""
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QStackedWidget, QLabel,
    QMessageBox, QApplication,
)
from PyQt5.QtCore import Qt, QEvent, QRectF, QRect
from PyQt5.QtGui import QIcon
from qfluentwidgets import (
    MSFluentWindow, NavigationInterface, NavigationItemPosition,
    FluentIcon, setTheme, Theme, InfoBar, InfoBarPosition,
    PushButton, FluentIconBase, drawIcon,
)
from qfluentwidgets.common.color import autoFallbackThemeColor
from qfluentwidgets.common.style_sheet import isDarkTheme
import json, os as _os
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT, WINDOW_TITLE, AppSettings,
)
from ui.add_question import AddQuestionPanel
from ui.question_list import QuestionListPanel
from ui.exam_panel import ExamPanel
from ui.settings_panel import SettingsPanel


def _patch_nav_button(btn):
    """Monkey-patch NavigationBarPushButton to enlarge icon and adjust layout
       — icon: 28×28 (from 20×20), shifted up to avoid text overlap
       — text: shifted down by 8px to give icon breathing room."""

    # Patch _drawIcon to render at 28×28
    orig_draw_icon = btn._drawIcon

    def patched_draw_icon(painter):
        if (btn.isPressed or not btn.isEnter) and \
           not (btn.isSelected or btn.isAboutSelected):
            painter.setOpacity(0.6)
        if not btn.isEnabled():
            painter.setOpacity(0.4)
        if btn._isSelectedTextVisible:
            rect = QRectF(16, 1, 28, 28)
        else:
            rect = QRectF(16, 1 + btn.iconAni.offset, 28, 28)
        selected = btn._selectedIcon or btn._icon
        if isinstance(selected, FluentIconBase) and \
           (btn.isSelected or btn.isAboutSelected):
            color = autoFallbackThemeColor(
                btn.lightSelectedColor, btn.darkSelectedColor)
            selected.render(painter, rect, fill=color.name())
        elif btn.isSelected or btn.isAboutSelected:
            drawIcon(selected, painter, rect)
        else:
            drawIcon(btn._icon, painter, rect)
    btn._drawIcon = patched_draw_icon

    # Patch _drawText to shift text down (from y=32 → y=38)
    def patched_draw_text(painter):
        if btn.isSelected and not btn._isSelectedTextVisible:
            return
        if btn.isSelected or btn.isAboutSelected:
            painter.setPen(autoFallbackThemeColor(
                btn.lightSelectedColor, btn.darkSelectedColor))
        else:
            painter.setPen(Qt.white if isDarkTheme() else Qt.black)
        painter.setFont(btn.font())
        rect = QRect(0, 38, btn.width(), 22)
        painter.drawText(rect, Qt.AlignCenter, btn.text())
    btn._drawText = patched_draw_text


class MainWindow(MSFluentWindow):
    """主窗口：Fluent 侧边栏 + QStackedWidget 切换 4 个功能面板"""

    def switchTo(self, interface):
        """切换面板并自动触发 on_shown（支持字符串 routeKey 和 QWidget）"""
        super().switchTo(interface)
        # 若传入的是字符串（routeKey），找到对应的 QWidget
        target = interface
        if isinstance(interface, str):
            for i in range(self.stackedWidget.count()):
                w = self.stackedWidget.widget(i)
                if w.objectName() == interface:
                    target = w
                    break
        try:
            if hasattr(target, 'on_shown') and not isinstance(target, str):
                target.on_shown()
        except Exception:
            pass

    def __init__(self):
        super().__init__()
        self.settings = AppSettings()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(900, 600)
        setTheme(Theme.AUTO)  # 跟随系统亮/暗色

        geo = self.settings.load_window_geometry()
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._load_app_icon()
        self._setup_panels()
        self._setup_navigation()
        self._connect_signals()

        # 加载全局样式表
        self._apply_stylesheet()

        # 加宽侧边栏 + 放大图标
        self._fix_sidebar()

        # 默认显示录入题目（switchTo 自动触发 on_shown）
        self.switchTo(self.add_question_panel)

        QApplication.instance().installEventFilter(self)

    # ── 面板 + 导航 ────────────────────────────────────────────────
    def _setup_panels(self):
        self.add_question_panel = AddQuestionPanel()
        self.question_list_panel = QuestionListPanel()
        self.exam_panel = ExamPanel()
        self.settings_panel = SettingsPanel()

        # 注册面板——使用中文名称 + 对应图标
        # (routeKey, panel, icon, position)
        panel_configs = [
            ("录入题目", self.add_question_panel, FluentIcon.EDIT,
             NavigationItemPosition.TOP),
            ("题库管理", self.question_list_panel, FluentIcon.LIBRARY,
             NavigationItemPosition.TOP),
            ("组卷考试", self.exam_panel, FluentIcon.EDUCATION,
             NavigationItemPosition.TOP),
            ("设置", self.settings_panel, FluentIcon.SETTING,
             NavigationItemPosition.BOTTOM),
        ]
        for route, panel, icon, pos in panel_configs:
            panel.setObjectName(route)
            self.addSubInterface(panel, icon, route, position=pos)

    def _setup_navigation(self):
        nav = self.navigationInterface

        # 底部版本标签
        ver_btn = PushButton("v1.0 — 王若水")
        ver_btn.setFlat(True)
        ver_btn.setStyleSheet("color: #888; font-size: 12px;")
        ver_btn.clicked.connect(self._show_version_info)
        nav.addWidget("versionLabel", ver_btn,
                       position=NavigationItemPosition.BOTTOM)

    def _fix_sidebar(self):
        """加宽侧边栏以适应中文文字 + 放大导航按钮图标 + 调整文字位置"""
        nav = self.navigationInterface
        # 侧边栏最小宽度（容纳中文 + 图标后仍有余量）
        nav.setMinimumWidth(100)

        # 放大每个导航按钮的图标并下移文字
        from qfluentwidgets.components.navigation.navigation_bar import \
            NavigationBarPushButton
        for btn in nav.findChildren(NavigationBarPushButton):
            try:
                _patch_nav_button(btn)
            except Exception:
                pass

    def _setup_menu(self):
        pass  # MSFluentWindow 不支持 QMenuBar，导航栏替代

    def _connect_signals(self):
        self.question_list_panel.edit_requested.connect(self._on_edit_question)
        self.settings_panel.font_changed.connect(self._on_font_changed)
        self.settings_panel.input_lines_changed.connect(self._on_input_lines_changed)
        self.settings_panel.image_mode_changed.connect(self._on_image_mode_changed)
        self.settings_panel.exam_default_changed.connect(self._on_exam_default_changed)

    # ── 导航回调 ──────────────────────────────────────────────────
    def _nav_to(self, idx):
        """跳转面板（switchTo 自动触发 on_shown）"""
        route_keys = ["录入题目", "题库管理", "组卷考试"]
        panels = [self.add_question_panel, self.question_list_panel,
                   self.exam_panel]
        if 0 <= idx < len(panels):
            self.navigationInterface.setCurrentItem(route_keys[idx])
            self.switchTo(panels[idx])

    def _show_settings(self):
        self.navigationInterface.setCurrentItem("设置")
        self.switchTo(self.settings_panel)

    def _on_edit_question(self, qid):
        self.navigationInterface.setCurrentItem("录入题目")
        self.switchTo(self.add_question_panel)
        self.add_question_panel.load_question(qid)

    # ── 全局样式 ──────────────────────────────────────────────────
    def _apply_stylesheet(self):
        """加载并应用全局 QSS 样式表"""
        try:
            qss_path = _os.path.join(_os.path.dirname(
                _os.path.abspath(__file__)), "styles.qss")
            if _os.path.exists(qss_path):
                qss = self.settings.build_stylesheet(qss_path)
                QApplication.instance().setStyleSheet(qss)
        except Exception:
            pass

    # ── 信号处理 ──────────────────────────────────────────────────
    def _on_font_changed(self):
        # 重新加载全局样式表（字号已通过 settings 更新）
        self._apply_stylesheet()
        # 更新各面板中的动态样式
        self.add_question_panel.update_input_heights()
        self.add_question_panel.update_dynamic_styles()
        self.exam_panel.update_dynamic_styles()
        self.question_list_panel.update_dynamic_styles()

    def _on_input_lines_changed(self):
        self.add_question_panel.update_input_heights()

    def _on_image_mode_changed(self):
        self.question_list_panel._do_search()

    def _on_exam_default_changed(self, count):
        self.exam_panel.set_default_count(count)

    def _switch_and_export(self):
        self.navigationInterface.setCurrentItem("题库管理")
        self.switchTo(self.question_list_panel)  # on_shown 已在 switchTo 中自动调用
        self.question_list_panel._export_questions()

    # ── 图标 + 关于 ───────────────────────────────────────────────
    def _load_app_icon(self):
        try:
            config_path = _os.path.join(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__))), "resources", "icon_config.json")
            if _os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                icon_name = cfg.get("app_icon", "")
                if icon_name:
                    icon_path = _os.path.join(_os.path.dirname(config_path),
                                              "icons", icon_name)
                    if _os.path.exists(icon_path):
                        self.setWindowIcon(QIcon(icon_path))
        except Exception:
            pass

    def _show_version_info(self):
        QMessageBox.about(self, "关于",
            "<h3>我的题库 v1.0</h3>"
            "<p>一款轻量级桌面题库管理软件</p>"
            "<p>作者：<b>王若水</b></p>"
        )

    # ── 窗口 + 缩放 ──────────────────────────────────────────────
    def closeEvent(self, event):
        self.settings.save_window_geometry(self.saveGeometry())
        super().closeEvent(event)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                delta = event.angleDelta().y()
                step = 5 if delta > 0 else -5
                self.settings.adjust_font_scale(step)
                self._on_font_changed()
                return True
        return super().eventFilter(obj, event)

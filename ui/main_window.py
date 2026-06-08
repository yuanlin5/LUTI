"""
=============================================================================
 主窗口 —— Fluent 侧边栏导航 + 多页面内容区
=============================================================================
"""
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QStackedWidget, QLabel,
    QMessageBox, QApplication,
)
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QIcon
from qfluentwidgets import (
    MSFluentWindow, NavigationInterface, NavigationItemPosition,
    FluentIcon, setTheme, Theme, InfoBar, InfoBarPosition,
    PushButton,
)
import json, os as _os
from config import (
    WINDOW_WIDTH, WINDOW_HEIGHT, WINDOW_TITLE, AppSettings,
)
from ui.add_question import AddQuestionPanel
from ui.question_list import QuestionListPanel
from ui.exam_panel import ExamPanel
from ui.settings_panel import SettingsPanel


class MainWindow(MSFluentWindow):
    """主窗口：Fluent 侧边栏 + QStackedWidget 切换 4 个功能面板"""

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
        self._setup_menu()
        self._connect_signals()

        # 默认显示录入题目
        self.switchTo(self.add_question_panel)
        self.add_question_panel.on_shown()

        QApplication.instance().installEventFilter(self)

    # ── 面板 + 导航 ────────────────────────────────────────────────
    def _setup_panels(self):
        self.add_question_panel = AddQuestionPanel()
        self.question_list_panel = QuestionListPanel()
        self.exam_panel = ExamPanel()
        self.settings_panel = SettingsPanel()

        # 设置 objectName（Fluent 要求不能为空字符串）
        for route, panel in [
            ("addQuestion", self.add_question_panel),
            ("questionList", self.question_list_panel),
            ("examPanel", self.exam_panel),
            ("settingsPanel", self.settings_panel),
        ]:
            panel.setObjectName(route)
            self.addSubInterface(panel, FluentIcon.HOME, route)

    def _setup_navigation(self):
        nav = self.navigationInterface

        nav.addItem("addQuestion", FluentIcon.EDIT, "录入题目",
                     onClick=lambda: self._nav_to(0))
        nav.addItem("questionList", FluentIcon.LIBRARY, "题库管理",
                     onClick=lambda: self._nav_to(1))
        nav.addItem("examPanel", FluentIcon.EDUCATION, "组卷考试",
                     onClick=lambda: self._nav_to(2))
        nav.addItem("settingsPanel", FluentIcon.SETTING, "设置",
                     onClick=lambda: self._show_settings(),
                     position=NavigationItemPosition.BOTTOM)

        # 底部版本标签（用 PushButton 替代 QLabel，因导航栏需要 clicked 信号）
        ver_btn = PushButton("v1.0 — 王若水")
        ver_btn.setFlat(True)
        ver_btn.setStyleSheet("color: #888; font-size: 12px;")
        ver_btn.clicked.connect(self._show_version_info)
        nav.addWidget("versionLabel", ver_btn,
                       position=NavigationItemPosition.BOTTOM)

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
        """跳转面板并触发 on_shown"""
        panels = [self.add_question_panel, self.question_list_panel,
                   self.exam_panel]
        if 0 <= idx < len(panels):
            self.switchTo(panels[idx])
            panels[idx].on_shown()

    def _show_settings(self):
        self.navigationInterface.setCurrentItem("settingsPanel")
        self.switchTo(self.settings_panel)
        self.settings_panel.on_shown()

    def _switch_and_export(self):
        self.switchTo(self.question_list_panel)
        self.question_list_panel.on_shown()
        self.question_list_panel._export_questions()

    def _on_edit_question(self, qid):
        self.navigationInterface.setCurrentItem("addQuestion")
        self.switchTo(self.add_question_panel)
        self.add_question_panel.load_question(qid)

    # ── 信号处理 ──────────────────────────────────────────────────
    def _on_font_changed(self):
        self.add_question_panel.update_input_heights()

    def _on_input_lines_changed(self):
        self.add_question_panel.update_input_heights()

    def _on_image_mode_changed(self):
        self.question_list_panel._do_search()

    def _on_exam_default_changed(self, count):
        self.exam_panel.set_default_count(count)

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

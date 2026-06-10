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

    def switchTo(self, interface):
        """切换面板并自动触发 on_shown"""
        super().switchTo(interface)
        if hasattr(interface, 'on_shown'):
            interface.on_shown()

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

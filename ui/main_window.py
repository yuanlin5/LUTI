"""
=============================================================================
 主窗口 —— Fluent 侧边栏导航 + 多页面内容区
=============================================================================
"""
import sys, subprocess
from PyQt5.QtWidgets import (
    QWidget, QHBoxLayout, QStackedWidget, QLabel,
    QMessageBox, QApplication,
)
from PyQt5.QtCore import Qt, QEvent, QRectF, QRect
from PyQt5.QtGui import QIcon, QFont
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


# ============================================================================
# 导航按钮增强 —— 放大图标 + 调整文字
# ============================================================================

def _patch_nav_button(btn):
    """图标左 + 文字右的横向布局，图标 24×24，按钮高度 44px，宽度按内容适配"""
    ICON_SZ = 24         # 图标大小
    ICON_X = 10          # 图标距左
    GAP = 8              # 图标与文字间距
    TEXT_RPAD = 14       # 文字右侧留白
    BTN_H = 44           # 按钮高度

    # 计算图标垂直居中
    icon_y = (BTN_H - ICON_SZ) // 2          # 44-24=20 → y=10
    # 文字起始 x = 图标右 + 间距
    text_x = ICON_X + ICON_SZ + GAP          # 10+24+8=42
    # 文字宽度 = 按钮宽 - 文字起始 - 右侧留白
    # 中文4个字约需80px（含字体放大余量），按钮宽=10+24+8+120+14=176
    BTN_MIN_W = ICON_X + ICON_SZ + GAP + 120 + TEXT_RPAD  # ≈176

    btn.setMinimumWidth(BTN_MIN_W)
    btn.setMaximumWidth(9999)
    btn.setMinimumHeight(BTN_H)
    btn.setMaximumHeight(BTN_H)              # 固定高度

    def patched_draw_icon(painter):
        if (btn.isPressed or not btn.isEnter) and \
           not (btn.isSelected or btn.isAboutSelected):
            painter.setOpacity(0.6)
        if not btn.isEnabled():
            painter.setOpacity(0.4)
        if btn._isSelectedTextVisible:
            rect = QRectF(ICON_X, icon_y, ICON_SZ, ICON_SZ)
        else:
            rect = QRectF(ICON_X, icon_y + btn.iconAni.offset, ICON_SZ, ICON_SZ)
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

    def patched_draw_text(painter):
        if btn.isSelected and not btn._isSelectedTextVisible:
            return
        if btn.isSelected or btn.isAboutSelected:
            painter.setPen(autoFallbackThemeColor(
                btn.lightSelectedColor, btn.darkSelectedColor))
        else:
            painter.setPen(Qt.white if isDarkTheme() else Qt.black)
        painter.setFont(btn.font())
        # 文字垂直居中，水平靠左（从 text_x 到 按钮右减留白）
        text_w = btn.width() - text_x - TEXT_RPAD
        rect = QRect(text_x, 0, text_w, BTN_H)
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, btn.text())
    btn._drawText = patched_draw_text


# ============================================================================
# 主窗口
# ============================================================================

class MainWindow(MSFluentWindow):
    """主窗口：Fluent 侧边栏 + QStackedWidget"""

    # ── switchTo：支持字符串路由键 ──
    def switchTo(self, interface):
        """切换面板（支持字符串 routeKey），切换后自动触发 on_shown()"""
        if isinstance(interface, str):
            for i in range(self.stackedWidget.count()):
                w = self.stackedWidget.widget(i)
                if w.objectName() == interface:
                    interface = w
                    break
        super().switchTo(interface)
        try:
            if hasattr(interface, 'on_shown') and not isinstance(interface, str):
                interface.on_shown()
        except Exception:
            pass

    # ── 构造 ──
    def __init__(self):
        super().__init__()
        self.settings = AppSettings()
        self.setWindowTitle(WINDOW_TITLE)
        self.setMinimumSize(900, 600)
        setTheme(Theme.AUTO)

        geo = self.settings.load_window_geometry()
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._load_app_icon()
        self._setup_panels()
        self._setup_navigation()
        self._connect_signals()
        self._apply_stylesheet()
        self._fix_sidebar()
        self._setup_restart_button()
        self.switchTo(self.add_question_panel)
        QApplication.instance().installEventFilter(self)

    # ── 面板注册 ──
    def _setup_panels(self):
        self.add_question_panel = AddQuestionPanel()
        self.question_list_panel = QuestionListPanel()
        self.exam_panel = ExamPanel()
        self.settings_panel = SettingsPanel()

        panel_configs = [
            ("录入题目", self.add_question_panel, FluentIcon.EDIT,
             NavigationItemPosition.TOP),
            ("题库管理", self.question_list_panel, FluentIcon.LIBRARY,
             NavigationItemPosition.TOP),
            ("组卷考试", self.exam_panel, FluentIcon.EDUCATION,
             NavigationItemPosition.TOP),
            ("设置",     self.settings_panel, FluentIcon.SETTING,
             NavigationItemPosition.BOTTOM),
        ]
        for route, panel, icon, pos in panel_configs:
            panel.setObjectName(route)
            self.addSubInterface(panel, icon, route, position=pos)

    # ── 导航栏 ──
    def _setup_navigation(self):
        nav = self.navigationInterface
        ver_btn = PushButton("v1.0 — 王若水")
        ver_btn.setFlat(True)
        ver_btn.setStyleSheet("color: #888; font-size: 12px;")
        ver_btn.clicked.connect(self._show_version_info)
        nav.addWidget("versionLabel", ver_btn,
                       position=NavigationItemPosition.BOTTOM)

    # ── 侧边栏微调 ──
    def _fix_sidebar(self):
        nav = self.navigationInterface

        from qfluentwidgets.components.navigation.navigation_bar import \
            NavigationBarPushButton

        # 先打补丁，让按钮获得正确的尺寸
        for btn in nav.findChildren(NavigationBarPushButton):
            try:
                _patch_nav_button(btn)
            except Exception:
                pass

        # 布局微调：间距 + 弹性撑开 ScrollArea（让底部按钮沉底）
        from PyQt5.QtWidgets import QVBoxLayout, QScrollArea
        for child in nav.children():
            if isinstance(child, QVBoxLayout):
                child.setSpacing(0)
                child.setContentsMargins(0, 4, 0, 4)
                # 找到 ScrollArea 所在位置，设置 stretch=1 让它撑满剩余空间
                for i in range(child.count()):
                    item = child.itemAt(i)
                    if item.widget() and isinstance(item.widget(), QScrollArea):
                        child.setStretch(i, 1)        # stretch=1 撑满
                        # 内部按钮面板：间距 + 弹性 spacer 推底部按钮
                        scroll = item.widget()
                        inner = scroll.widget()
                        if inner and inner.layout():
                            il = inner.layout()
                            il.setSpacing(6)
                            il.setContentsMargins(8, 0, 8, 0)
                            # 找到"设置"前面的位置插入 stretch spacer
                            for j in range(il.count()):
                                it = il.itemAt(j)
                                if it and it.widget():
                                    txt = it.widget().text() if hasattr(it.widget(), 'text') else ''
                                    if '设置' in txt:
                                        il.insertStretch(j, 1)
                                        break
                        break
                break

        # 侧栏宽度
        nav.setMinimumWidth(165)

    # ── 一键重启 ──
    def _setup_restart_button(self):
        """右下角临时重启按钮"""
        self._restart_btn = PushButton("⟳ 重启")
        self._restart_btn.setFixedSize(80, 32)
        self._restart_btn.setStyleSheet("""
            PushButton {
                background: #0078D4; color: white;
                border-radius: 6px; font-size: 13px; font-weight: bold;
            }
            PushButton:hover {
                background: #106EBE;
            }
            PushButton:pressed {
                background: #005A9E;
            }
        """)
        self._restart_btn.clicked.connect(self._restart_app)
        self._restart_btn.setParent(self)
        self._restart_btn.raise_()
        self._restart_btn.show()

    def _restart_app(self):
        """重启应用程序"""
        reply = QMessageBox.question(
            self, "确认重启", "确定要重启软件吗？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            subprocess.Popen([sys.executable] + sys.argv)
            QApplication.quit()

    def _position_restart_button(self):
        """将重启按钮定位到窗口右下角"""
        x = self.width() - self._restart_btn.width() - 20
        y = self.height() - self._restart_btn.height() - 20
        self._restart_btn.move(x, y)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_restart_btn'):
            self._position_restart_button()

    # ── 信号连接 ──
    def _connect_signals(self):
        self.question_list_panel.edit_requested.connect(self._on_edit_question)
        self.settings_panel.font_changed.connect(self._on_font_changed)
        self.settings_panel.input_lines_changed.connect(self._on_input_lines_changed)
        self.settings_panel.image_mode_changed.connect(self._on_image_mode_changed)
        self.settings_panel.exam_default_changed.connect(self._on_exam_default_changed)
        self.settings_panel.shortcut_changed.connect(self._on_shortcut_changed)

    # ── 导航 ──
    def _nav_to(self, idx):
        route_keys = ["录入题目", "题库管理", "组卷考试"]
        panels = [self.add_question_panel, self.question_list_panel, self.exam_panel]
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

    # ── 样式 ──
    def _apply_stylesheet(self):
        try:
            qss_path = _os.path.join(_os.path.dirname(
                _os.path.abspath(__file__)), "styles.qss")
            if _os.path.exists(qss_path):
                qss = self.settings.build_stylesheet(qss_path)
                QApplication.instance().setStyleSheet(qss)
        except Exception:
            pass

    # ── 信号处理 ──
    def _on_font_changed(self):
        self._apply_stylesheet()
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

    def _on_shortcut_changed(self):
        """快捷键变更时无需额外操作——QuestionListPanel 在每次按键时动态读取"""
        pass

    def _switch_and_export(self):
        self.navigationInterface.setCurrentItem("题库管理")
        self.switchTo(self.question_list_panel)
        self.question_list_panel._export_questions()

    # ── 图标 ──
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

    # ── 窗口事件 ──
    def closeEvent(self, event):
        self.settings.save_window_geometry(self.saveGeometry())
        super().closeEvent(event)

    # ── 全局事件（仅 Ctrl+滚轮）──
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ControlModifier:
                delta = event.angleDelta().y()
                step = 5 if delta > 0 else -5
                self.settings.adjust_font_scale(step)
                self._on_font_changed()
                return True
        return super().eventFilter(obj, event)

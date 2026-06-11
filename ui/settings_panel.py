"""
设置页面面板。

提供应用全局设置的图形化配置界面，包括：
- 字体大小调节（滑块 + 百分比标签，实时生效）
- 输入框显示行数
- 图片显示模式（缩略图 / 原图）
- 考试默认抽题数量

所有设置通过 AppSettings 持久化，变更时发出对应的 pyqtSignal 通知其他模块。
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QFrame, QSlider, QScrollArea, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from qfluentwidgets import (
    PrimaryPushButton, PushButton, ComboBox, CardWidget, SmoothScrollArea,
)
from config import AppSettings


class ShortcutCaptureButton(PushButton):
    """快捷键捕获按钮：点击后按下新快捷键即可修改"""
    shortcut_captured = pyqtSignal(str, str)  # action_id, new_key_sequence

    def __init__(self, action_id, current_key, parent=None):
        super().__init__(parent)
        self.setText(current_key)
        self.action_id = action_id
        self._capturing = False
        self._normal_text = current_key
        self.setObjectName("secondaryBtn")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(150)
        self.clicked.connect(self._start_capture)

    def _start_capture(self):
        self._capturing = True
        self.setText("按下快捷键...")
        self.setStyleSheet(
            "PushButton { border: 2px solid #4A90D9; background: #FFF8E1;"
            " color: #333; font-weight: bold; border-radius: 6px; padding: 6px 12px; }")
        self.setFocus()

    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        modifiers = []
        if event.modifiers() & Qt.ControlModifier:
            modifiers.append("Ctrl")
        if event.modifiers() & Qt.ShiftModifier:
            modifiers.append("Shift")
        if event.modifiers() & Qt.AltModifier:
            modifiers.append("Alt")
        key = event.key()
        # 跳过纯修饰键
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return
        from PyQt5.QtGui import QKeySequence
        key_name = QKeySequence(key).toString()
        if key_name and modifiers:
            seq = "+".join(modifiers + [key_name])
        elif key_name:
            seq = key_name
        else:
            seq = ""
        self._capturing = False
        self._normal_text = seq
        self.setText(seq if seq else "未设置")
        self.setStyleSheet("")
        self.shortcut_captured.emit(self.action_id, seq)
        self.clearFocus()


class SettingsPanel(QWidget):
    font_changed = pyqtSignal()
    input_lines_changed = pyqtSignal()
    image_mode_changed = pyqtSignal()
    exam_default_changed = pyqtSignal(int)
    shortcut_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = AppSettings()
        self._setup_ui()

    def _setup_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        scroll.setWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)

        title = QLabel("设置")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # ---- 字体大小 ----
        # 使用水平滑块调节字体缩放比例（80%-200%），支持 Ctrl+滚轮
        font_frame = QFrame()
        font_frame.setObjectName("card")
        font_layout = QVBoxLayout(font_frame)
        font_layout.setContentsMargins(20, 16, 20, 16)
        font_layout.setSpacing(12)

        t = QLabel("字体大小")
        t.setObjectName("sectionTitle")
        font_layout.addWidget(t)
        d = QLabel("调整后立即生效，也可按住 Ctrl + 鼠标滚轮缩放")
        d.setObjectName("sectionDesc")
        font_layout.addWidget(d)

        slider_row = QHBoxLayout()
        slider_row.setSpacing(12)

        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(AppSettings.MIN_SCALE, AppSettings.MAX_SCALE)
        self.font_slider.setValue(self.settings.font_scale)
        self.font_slider.setTickPosition(QSlider.TicksBelow)
        self.font_slider.setTickInterval(10)
        self.font_slider.valueChanged.connect(self._on_slider_changed)
        slider_row.addWidget(self.font_slider, 1)

        self.font_pct_label = QLabel(f"{self.settings.font_scale}%")
        self.font_pct_label.setMinimumWidth(50)
        self.font_pct_label.setAlignment(Qt.AlignCenter)
        slider_row.addWidget(self.font_pct_label)

        font_layout.addLayout(slider_row)

        scale_hint = QHBoxLayout()
        scale_hint.addWidget(QLabel("80%"))
        scale_hint.addStretch()
        scale_hint.addWidget(QLabel("140%"))
        scale_hint.addStretch()
        scale_hint.addWidget(QLabel("200%"))
        font_layout.addLayout(scale_hint)

        layout.addWidget(font_frame)

        # ---- 输入框行数 ----
        # 控制题目/答案/备注输入框的显示行数（3~20 行）
        input_frame = QFrame()
        input_frame.setObjectName("card")
        input_layout = QVBoxLayout(input_frame)
        input_layout.setContentsMargins(20, 16, 20, 16)
        input_layout.setSpacing(8)

        t = QLabel("输入框行数")
        t.setObjectName("sectionTitle")
        input_layout.addWidget(t)
        d = QLabel("调整题目、答案、备注输入框显示的行数")
        d.setObjectName("sectionDesc")
        input_layout.addWidget(d)

        in_row = QHBoxLayout()
        in_row.addWidget(QLabel("显示行数："))
        self.input_lines_spin = QSpinBox()
        self.input_lines_spin.setRange(3, 20)
        self.input_lines_spin.setValue(self.settings.input_lines)
        self.input_lines_spin.valueChanged.connect(self._on_input_lines_changed)
        in_row.addWidget(self.input_lines_spin)
        in_row.addStretch()
        input_layout.addLayout(in_row)

        layout.addWidget(input_frame)

        # ---- 图片显示模式 ----
        # 切换题库管理页面中图片的展示方式：缩略图（thumb）或原图（full）
        img_frame = QFrame()
        img_frame.setObjectName("card")
        img_layout = QVBoxLayout(img_frame)
        img_layout.setContentsMargins(20, 16, 20, 16)
        img_layout.setSpacing(8)

        t = QLabel("图片显示")
        t.setObjectName("sectionTitle")
        img_layout.addWidget(t)
        d = QLabel("切换题库管理页面中图片的显示方式")
        d.setObjectName("sectionDesc")
        img_layout.addWidget(d)

        img_row = QHBoxLayout()
        img_row.addWidget(QLabel("显示模式："))
        self.image_mode_combo = ComboBox()
        self.image_mode_combo.addItem("缩略图（小图）", "thumb")
        self.image_mode_combo.addItem("原图（大图）", "full")
        idx = self.image_mode_combo.findData(self.settings.image_display_mode)
        self.image_mode_combo.setCurrentIndex(max(0, idx))
        self.image_mode_combo.currentIndexChanged.connect(self._on_image_mode_changed)
        img_row.addWidget(self.image_mode_combo)
        img_row.addStretch()
        img_layout.addLayout(img_row)

        q_row = QHBoxLayout()
        q_row.addWidget(QLabel("压缩比例："))
        self.image_quality_combo = ComboBox()
        self.image_quality_combo.addItem("35%", 35)
        self.image_quality_combo.addItem("50%（推荐）", 50)
        self.image_quality_combo.addItem("75%", 75)
        self.image_quality_combo.addItem("100%（原图）", 100)
        idx_q = self.image_quality_combo.findData(self.settings.image_quality)
        self.image_quality_combo.setCurrentIndex(max(0, idx_q))
        self.image_quality_combo.currentIndexChanged.connect(self._on_image_quality_changed)
        q_row.addWidget(self.image_quality_combo)
        q_row.addStretch()
        img_layout.addLayout(q_row)

        layout.addWidget(img_frame)

        # ---- 文件夹路径管理 ----
        folder_frame = QFrame()
        folder_frame.setObjectName("card")
        folder_layout = QVBoxLayout(folder_frame)
        folder_layout.setContentsMargins(20, 16, 20, 16)
        folder_layout.setSpacing(12)

        t = QLabel("文件夹管理")
        t.setObjectName("sectionTitle")
        folder_layout.addWidget(t)

        from config import DB_PATH, IMAGE_DIR, BASE_DIR
        self._folder_paths = {"题库数据": DB_PATH, "图片存储": IMAGE_DIR, "软件根目录": BASE_DIR}
        for label, path in [("题库数据", DB_PATH), ("图片存储", IMAGE_DIR),
                            ("软件根目录", BASE_DIR)]:
            r = QHBoxLayout()
            r.addWidget(QLabel(f"{label}："))
            p = QLabel(path)
            p.setStyleSheet("color: #333; font-size: 16px;")
            p.setWordWrap(True)
            r.addWidget(p, 1)
            btn = PushButton("更改")
            btn.setObjectName("smallBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, lb=label, pl=p:
                self._change_folder(lb, pl))
            r.addWidget(btn)
            folder_layout.addLayout(r)

        layout.addWidget(folder_frame)

        # ---- 默认抽题数 ----
        # 设置考试模式每次默认抽取的题目数量（1~100 道）
        exam_frame = QFrame()
        exam_frame.setObjectName("card")
        exam_layout = QVBoxLayout(exam_frame)
        exam_layout.setContentsMargins(20, 16, 20, 16)
        exam_layout.setSpacing(12)

        t = QLabel("考试默认值")
        t.setObjectName("sectionTitle")
        exam_layout.addWidget(t)

        count_layout = QHBoxLayout()
        count_layout.addWidget(QLabel("默认抽题数量："))
        self.exam_count_spin = QSpinBox()
        self.exam_count_spin.setRange(1, 100)
        self.exam_count_spin.setValue(self.settings.default_exam_count)
        count_layout.addWidget(self.exam_count_spin)
        count_layout.addStretch()
        exam_layout.addLayout(count_layout)

        layout.addWidget(exam_frame)

        # ---- 快捷键设置 ----
        shortcut_frame = QFrame()
        shortcut_frame.setObjectName("card")
        shortcut_layout = QVBoxLayout(shortcut_frame)
        shortcut_layout.setContentsMargins(20, 16, 20, 16)
        shortcut_layout.setSpacing(8)

        t = QLabel("快捷键设置")
        t.setObjectName("sectionTitle")
        shortcut_layout.addWidget(t)
        d = QLabel("点击按钮后按下新的快捷键即可修改，支持 Ctrl/Shift/Alt 组合键")
        d.setObjectName("sectionDesc")
        shortcut_layout.addWidget(d)

        shortcut_scroll = QScrollArea()
        shortcut_scroll.setWidgetResizable(True)
        shortcut_scroll.setFrameShape(QFrame.NoFrame)
        shortcut_scroll.setMaximumHeight(400)
        shortcut_inner = QWidget()
        shortcut_form = QVBoxLayout(shortcut_inner)
        shortcut_form.setSpacing(8)

        self._shortcut_buttons = {}
        shortcut_labels = {
            "select_all": "全选工作表",
            "goto_dialog": "定位 (Go To)",
            "select_col": "选中当前列",
            "select_row": "选中当前行",
            "select_region": "选中数据区域",
            "jump_edge_up": "跳转到数据区域顶部",
            "jump_edge_down": "跳转到数据区域底部",
            "jump_edge_left": "跳转到数据区域左侧",
            "jump_edge_right": "跳转到数据区域右侧",
            "expand_up": "向上扩展选择",
            "expand_down": "向下扩展选择",
            "expand_left": "向左扩展选择",
            "expand_right": "向右扩展选择",
            "prev_page": "上一页",
            "next_page": "下一页",
            "clear_selection": "清除选择",
        }

        for action_id, label in shortcut_labels.items():
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel(label + "：")
            lbl.setMinimumWidth(160)
            row.addWidget(lbl)
            current = self.settings.get_shortcut(action_id)
            btn = ShortcutCaptureButton(action_id, current)
            btn.shortcut_captured.connect(self._on_shortcut_captured)
            self._shortcut_buttons[action_id] = btn
            row.addWidget(btn, 1)
            row.addStretch()
            shortcut_form.addLayout(row)

        shortcut_scroll.setWidget(shortcut_inner)
        shortcut_layout.addWidget(shortcut_scroll)

        reset_row = QHBoxLayout()
        reset_row.addStretch()
        reset_btn = PushButton("恢复默认快捷键")
        reset_btn.setObjectName("secondaryBtn")
        reset_btn.clicked.connect(self._reset_shortcuts)
        reset_row.addWidget(reset_btn)
        shortcut_layout.addLayout(reset_row)

        layout.addWidget(shortcut_frame)

        # ---- 保存按钮 ----
        # 点击后将考试默认抽题数写入配置，显示成功提示
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.status_label = QLabel()
        self.status_label.setObjectName("statusLabel")
        btn_layout.addWidget(self.status_label)

        save_btn = PushButton("保存设置")
        save_btn.setObjectName("primaryBtn")
        save_btn.clicked.connect(self._save_settings)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _on_slider_changed(self, value):
        """字体滑块值变更时同步更新百分比标签、持久化设置并发出通知。"""
        self.font_pct_label.setText(f"{value}%")
        self.settings.set_font_scale(value)
        self.font_changed.emit()

    def _on_input_lines_changed(self, value):
        self.settings.set_input_lines(value)
        self.input_lines_changed.emit()

    def _on_image_mode_changed(self):
        mode = self.image_mode_combo.currentData()
        self.settings.set_image_display_mode(mode)
        self.image_mode_changed.emit()

    def _on_image_quality_changed(self):
        q = self.image_quality_combo.currentData()
        self.settings.set_image_quality(q)

    def _save_settings(self):
        """保存考试默认抽题数到配置，更新状态提示并发出变更信号。"""
        new_count = self.exam_count_spin.value()
        self.settings.set_default_exam_count(new_count)
        self.status_label.setText("设置已保存")
        base_size = self.settings.get_font_sizes()[0]
        self.status_label.setStyleSheet(f"color: #52C41A; font-size: {base_size}px;")
        self.exam_default_changed.emit(new_count)

    def get_default_exam_count(self):
        return self.settings.default_exam_count

    def _change_folder(self, label, path_label):
        """打开文件夹选择对话框（起始位置为当前路径）"""
        from PyQt5.QtWidgets import QFileDialog
        current = path_label.text()
        path = QFileDialog.getExistingDirectory(self, f"选择{label}文件夹", current)
        if path:
            path_label.setText(path)
            path_label.setStyleSheet("color: #333; font-size: 16px;")
            self.status_label.setText(f"{label}路径已更新（重启生效）")
            self.status_label.setStyleSheet("color: #F5A623;")

    def _on_shortcut_captured(self, action_id, key_sequence):
        """快捷键修改后保存并通知"""
        if key_sequence:
            self.settings.set_shortcut(action_id, key_sequence)
        self.shortcut_changed.emit()

    def _reset_shortcuts(self):
        """恢复所有快捷键为默认值"""
        self.settings.reset_all_shortcuts()
        for action_id, btn in self._shortcut_buttons.items():
            default = self.settings.get_shortcut(action_id)
            btn.setText(default)
            btn._normal_text = default
        self.shortcut_changed.emit()

    def on_shown(self):
        """页面每次显示时将控件值重置为 Settings 中的最新值，确保与外部修改保持同步。"""
        self.font_slider.setValue(self.settings.font_scale)
        self.input_lines_spin.setValue(self.settings.input_lines)
        idx = self.image_mode_combo.findData(self.settings.image_display_mode)
        self.image_mode_combo.setCurrentIndex(max(0, idx))
        idx_q = self.image_quality_combo.findData(self.settings.image_quality)
        self.image_quality_combo.setCurrentIndex(max(0, idx_q))
        self.exam_count_spin.setValue(self.settings.default_exam_count)
        self.status_label.clear()
        # 刷新快捷键按钮显示
        for action_id, btn in self._shortcut_buttons.items():
            current = self.settings.get_shortcut(action_id)
            btn.setText(current)
            btn._normal_text = current
        self.update_dynamic_styles()

    def update_dynamic_styles(self):
        """字体缩放后重新应用动态样式"""
        s = AppSettings()
        style = s.build_dynamic_style
        self.status_label.setStyleSheet(
            style("color: #52C41A; font-size: {font_base}px;"))

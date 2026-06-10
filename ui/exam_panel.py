"""
考试面板 - Exam Panel

实现完整的考试工作流，分为三个阶段：
  1. 组卷设置 (setup_frame)  —— 选择题目数量、分类/标签筛选，点击开始考试
  2. 答题区   (answer_frame)  —— 逐题展示，用户可查看答案并判断正确/错误
  3. 结果区   (result_frame)  —— 统计正确/错误/未答题数及正确率，提供"再来一次"入口

支持键盘快捷键：←/→ 方向键翻题，空格键显示答案。
"""
import os
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSpinBox, QFrame, QTextEdit, QMessageBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap, QKeyEvent
from qfluentwidgets import (
    PrimaryPushButton, PushButton, ComboBox, CardWidget,
)
from database import models
from services.exam_service import generate_exam_questions, record_answer
from config import AppSettings


class ExamPanel(QWidget):
    """考试面板：组卷设置 -> 答题判断 -> 结果展示"""

    def __init__(self):
        super().__init__()
        self.current_exam_id = None        # 当前考试记录 ID（答题前创建）
        self.questions = []                # 本次考试的题目列表
        self.current_index = 0             # 当前显示的题目索引
        self.answer_status = {}            # {index: None/False/True}  各题判断状态
        self.judged_count = 0              # 已判断的题目数量
        self.settings = AppSettings()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)

        title = QLabel("组卷考试")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # ====== 阶段1：组卷设置 (setup_frame) ======
        # 用户在此选择题目数量、分类/标签筛选条件，点击"开始考试"进入答题阶段
        self.setup_frame = QFrame()
        self.setup_frame.setObjectName("card")
        setup_layout = QVBoxLayout(self.setup_frame)
        setup_layout.setContentsMargins(20, 16, 20, 16)
        setup_layout.setSpacing(12)

        setup_layout.addWidget(QLabel("组卷设置"))
        setup_layout.addWidget(QLabel("自定义抽题条件，生成专属试卷"))

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("题目数量："))
        self.num_spin = QSpinBox()
        self.num_spin.setRange(1, 100)
        self.num_spin.setValue(self.settings.default_exam_count)
        row1.addWidget(self.num_spin)
        row1.addStretch()
        setup_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("分类筛选："))
        self.exam_cat_filter = ComboBox()
        row2.addWidget(self.exam_cat_filter)
        row2.addWidget(QLabel("标签筛选："))
        self.exam_tag_filter = ComboBox()
        row2.addWidget(self.exam_tag_filter)
        row2.addStretch()
        setup_layout.addLayout(row2)

        self.start_btn = PushButton("开始考试")
        self.start_btn.setObjectName("primaryBtn")
        self.start_btn.clicked.connect(self._start_exam)
        setup_layout.addWidget(self.start_btn, alignment=Qt.AlignCenter)

        layout.addWidget(self.setup_frame)

        # ====== 阶段2：答题区 (answer_frame) ======
        # 逐题展示题目内容与图片，用户点击"显示答案"后通过"正确/错误"按钮进行判断
        # 已判断的题目回显答案和判断结果，禁止二次判断
        self.answer_frame = QFrame()
        self.answer_frame.setObjectName("card")
        self.answer_frame.setVisible(False)
        self.answer_frame.setFocusPolicy(Qt.StrongFocus)
        answer_layout = QVBoxLayout(self.answer_frame)
        answer_layout.setContentsMargins(20, 16, 20, 16)
        answer_layout.setSpacing(12)

        self.progress_label = QLabel()
        self.progress_label.setObjectName("statusLabel")
        answer_layout.addWidget(self.progress_label)

        self.question_display = QTextEdit()
        self.question_display.setReadOnly(True)
        self.question_display.setMaximumHeight(150)
        self.question_display.setPlaceholderText("题目内容...")
        answer_layout.addWidget(self.question_display)

        self.question_images_layout = QHBoxLayout()
        self.question_images_layout.setSpacing(10)
        answer_layout.addLayout(self.question_images_layout)

        self.show_answer_btn = PushButton("显示答案")
        self.show_answer_btn.setObjectName("primaryBtn")
        self.show_answer_btn.clicked.connect(self._show_answer)
        answer_layout.addWidget(self.show_answer_btn, alignment=Qt.AlignCenter)

        self.answer_display = QTextEdit()
        self.answer_display.setReadOnly(True)
        self.answer_display.setMaximumHeight(120)
        self.answer_display.setVisible(False)
        answer_layout.addWidget(self.answer_display)

        self.answer_images_layout = QHBoxLayout()
        self.answer_images_layout.setSpacing(10)
        self.answer_images_layout_widget = QWidget()
        self.answer_images_layout_widget.setLayout(self.answer_images_layout)
        self.answer_images_layout_widget.setVisible(False)
        answer_layout.addWidget(self.answer_images_layout_widget)

        # 判断状态提示（正确/错误标签）
        self.judge_status_label = QLabel()
        self.judge_status_label.setAlignment(Qt.AlignCenter)
        self.judge_status_label.setVisible(False)
        answer_layout.addWidget(self.judge_status_label)

        # 导航 + 判断按钮行
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(15)
        nav_layout.addStretch()

        self.prev_btn = PushButton("◀ 上一题")
        self.prev_btn.setObjectName("secondaryBtn")
        self.prev_btn.clicked.connect(self._prev_question)
        nav_layout.addWidget(self.prev_btn)

        self.correct_btn = PushButton("✓ 正确")
        self.correct_btn.setObjectName("correctBtn")
        self.correct_btn.clicked.connect(lambda: self._judge(False))
        nav_layout.addWidget(self.correct_btn)

        self.wrong_btn = PushButton("✗ 错误")
        self.wrong_btn.setObjectName("wrongBtn")
        self.wrong_btn.clicked.connect(lambda: self._judge(True))
        nav_layout.addWidget(self.wrong_btn)

        self.next_btn = PushButton("下一题 ▶")
        self.next_btn.setObjectName("secondaryBtn")
        self.next_btn.clicked.connect(self._next_question)
        nav_layout.addWidget(self.next_btn)

        nav_layout.addStretch()

        self.nav_widget = QWidget()
        self.nav_widget.setLayout(nav_layout)
        self.nav_widget.setVisible(False)
        answer_layout.addWidget(self.nav_widget)

        # 快捷键提示
        hint = QLabel("提示：显示答案后可用键盘 ← → 方向键翻阅题目")
        hint.setObjectName("statusLabel")
        hint.setAlignment(Qt.AlignCenter)
        answer_layout.addWidget(hint)

        layout.addWidget(self.answer_frame)

        # ====== 阶段3：结果区 (result_frame) ======
        # 考试结束后显示统计结果：正确数、错误数、正确率及鼓励语
        self.result_frame = QFrame()
        self.result_frame.setObjectName("card")
        self.result_frame.setVisible(False)
        result_layout = QVBoxLayout(self.result_frame)
        result_layout.setContentsMargins(20, 16, 20, 16)
        result_layout.setSpacing(12)

        self.result_title = QLabel("考试结果")
        title_size = self.settings.get_font_sizes()[1]
        self.result_title.setStyleSheet(
            f"font-size: {title_size}px; font-weight: bold; color: #333333;")
        result_layout.addWidget(self.result_title, alignment=Qt.AlignCenter)

        self.result_stats = QLabel()
        self.result_stats.setAlignment(Qt.AlignCenter)
        big_size = self.settings.get_font_sizes()[6]
        self.result_stats.setStyleSheet(
            f"font-size: {big_size}px; color: #333333;")
        result_layout.addWidget(self.result_stats)

        self.result_detail = QLabel()
        self.result_detail.setAlignment(Qt.AlignCenter)
        self.result_detail.setWordWrap(True)
        result_layout.addWidget(self.result_detail)

        self.retry_btn = PushButton("再来一次")
        self.retry_btn.setObjectName("primaryBtn")
        self.retry_btn.clicked.connect(self._reset_exam)
        result_layout.addWidget(self.retry_btn, alignment=Qt.AlignCenter)

        layout.addWidget(self.result_frame)
        layout.addStretch()

    def set_default_count(self, count):
        """由外部（如设置面板）更新默认题目数量到 spin 控件"""
        self.num_spin.setValue(count)

    def keyPressEvent(self, event):
        """键盘事件处理：
        - 答题阶段，← 键翻到上一题
        - 答题阶段，→ 键翻到下一题
        - 答题阶段，空格键显示答案（仅在按钮可见时生效）
        """
        if self.answer_frame.isVisible():
            if event.key() == Qt.Key_Left:
                self._prev_question()
                return
            elif event.key() == Qt.Key_Right:
                self._next_question()
                return
            elif event.key() == Qt.Key_Space:
                if self.show_answer_btn.isVisible():
                    self._show_answer()
                return
        super().keyPressEvent(event)

    def _refresh_exam_filters(self):
        """重新加载分类和标签筛选下拉框"""
        self.exam_cat_filter.clear()
        self.exam_cat_filter.addItem("不限分类", None)
        for cat in models.get_all_categories():
            self.exam_cat_filter.addItem(cat["name"], cat["id"])

        self.exam_tag_filter.clear()
        self.exam_tag_filter.addItem("不限标签", None)
        for tag in models.get_all_tags():
            self.exam_tag_filter.addItem(tag["name"], tag["id"])

    def _start_exam(self):
        """开始考试：
        1. 读取设置区选择的数量、分类、标签
        2. 调用 generate_exam_questions 抽题
        3. 在数据库创建考试记录
        4. 初始化 answer_status 和 judged_count
        5. 切换到答题界面并显示第一题
        """
        total = self.num_spin.value()
        cat_id = self.exam_cat_filter.currentData()
        tag_id = self.exam_tag_filter.currentData()

        self.questions = generate_exam_questions(total, cat_id, tag_id)

        if not self.questions:
            QMessageBox.information(self, "提示", "题库中没有符合条件的题目，请先录入题目或放宽筛选条件。")
            return

        actual_total = len(self.questions)
        title = f"考试 {datetime.now().strftime('%m-%d %H:%M')}"
        self.current_exam_id = models.create_exam(title, actual_total)

        self.current_index = 0
        self.answer_status = {i: None for i in range(actual_total)}
        self.judged_count = 0

        self.setup_frame.setVisible(False)
        self.result_frame.setVisible(False)
        self.answer_frame.setVisible(True)
        self.answer_frame.setFocus()

        self._show_current_question()

    def _show_current_question(self):
        """刷新答题区以显示 current_index 对应的题目：
        - 若该题已判断：回显答案内容和图片，显示之前的判断结果（正确/错误），禁用判断按钮
        - 若该题未判断：只显示题目和"显示答案"按钮，等待用户操作
        """
        q = self.questions[self.current_index]
        total = len(self.questions)
        status = self.answer_status.get(self.current_index)

        # 进度显示
        self.progress_label.setText(
            f"第 {self.current_index + 1} / {total} 题  已判断: {self.judged_count} 题"
        )

        self.question_display.setText(q["question_text"] or "[图片题目]")

        self._clear_layout(self.question_images_layout)
        self._clear_layout(self.answer_images_layout)

        images = models.get_question_images(q["id"])
        for img in images:
            if img["image_type"] == "question" and os.path.exists(img["image_path"]):
                pixmap = QPixmap(img["image_path"])
                if pixmap.width() > 400:
                    pixmap = pixmap.scaledToWidth(400, Qt.SmoothTransformation)
                lbl = QLabel()
                lbl.setPixmap(pixmap)
                self.question_images_layout.addWidget(lbl)

        # 已判断过的题目：回显结果
        if status is not None:
            self.answer_display.setText(q["answer_text"] or "[图片答案]")
            self.answer_display.setVisible(True)

            for img in images:
                if img["image_type"] == "answer" and os.path.exists(img["image_path"]):
                    pixmap = QPixmap(img["image_path"])
                    if pixmap.width() > 400:
                        pixmap = pixmap.scaledToWidth(400, Qt.SmoothTransformation)
                    lbl = QLabel()
                    lbl.setPixmap(pixmap)
                    self.answer_images_layout.addWidget(lbl)
            self.answer_images_layout_widget.setVisible(True)

            self.show_answer_btn.setVisible(False)
            self.correct_btn.setEnabled(False)
            self.wrong_btn.setEnabled(False)
            self.nav_widget.setVisible(True)

            if status:
                self.judge_status_label.setText("✗ 本题已判为：错误")
                self.judge_status_label.setStyleSheet(
                    "color: #FF4D4F; font-weight: bold; font-size: %dpx;" % AppSettings().get_font_sizes()[0]
                )
            else:
                self.judge_status_label.setText("✓ 本题已判为：正确")
                self.judge_status_label.setStyleSheet(
                    "color: #52C41A; font-weight: bold; font-size: %dpx;" % AppSettings().get_font_sizes()[0]
                )
            self.judge_status_label.setVisible(True)

            self._update_nav_buttons()
            return

        # 未判断：重置显示
        self.answer_display.clear()
        self.answer_display.setVisible(False)
        self.answer_images_layout_widget.setVisible(False)
        self.judge_status_label.setVisible(False)
        self.show_answer_btn.setVisible(True)
        self.correct_btn.setEnabled(True)
        self.wrong_btn.setEnabled(True)
        self.nav_widget.setVisible(False)

        self._update_nav_buttons()

    def _update_nav_buttons(self):
        """根据当前题号更新上下题导航按钮的启用/禁用状态"""
        self.prev_btn.setEnabled(self.current_index > 0)
        self.next_btn.setEnabled(self.current_index < len(self.questions) - 1)

    def _show_answer(self):
        """显示当前题目的答案文本和答案图片，隐藏"显示答案"按钮，显示导航/判断按钮"""
        q = self.questions[self.current_index]
        self.answer_display.setText(q["answer_text"] or "[图片答案]")
        self.answer_display.setVisible(True)
        self.answer_images_layout_widget.setVisible(True)
        self.show_answer_btn.setVisible(False)
        self.nav_widget.setVisible(True)

        images = models.get_question_images(q["id"])
        for img in images:
            if img["image_type"] == "answer" and os.path.exists(img["image_path"]):
                pixmap = QPixmap(img["image_path"])
                if pixmap.width() > 400:
                    pixmap = pixmap.scaledToWidth(400, Qt.SmoothTransformation)
                lbl = QLabel()
                lbl.setPixmap(pixmap)
                self.answer_images_layout.addWidget(lbl)

        self._update_nav_buttons()
        self.answer_frame.setFocus()

    def _judge(self, is_wrong):
        """对当前题目进行判断：
        - is_wrong=True 表示判错，is_wrong=False 表示判对
        - 若该题已判断过则直接返回（防止重复判断）
        - 调用 record_answer 写入答题记录并递增 wrong_count
        - 所有题目判断完毕时自动跳转结果页
        """
        if self.answer_status.get(self.current_index) is not None:
            return

        q = self.questions[self.current_index]
        record_answer(self.current_exam_id, q["id"], is_wrong)
        self.answer_status[self.current_index] = is_wrong
        self.judged_count += 1

        self.correct_btn.setEnabled(False)
        self.wrong_btn.setEnabled(False)

        if is_wrong:
            self.judge_status_label.setText("✗ 本题已判为：错误")
            self.judge_status_label.setStyleSheet(
                "color: #FF4D4F; font-weight: bold; font-size: %dpx;" % AppSettings().get_font_sizes()[0]
            )
        else:
            self.judge_status_label.setText("✓ 本题已判为：正确")
            self.judge_status_label.setStyleSheet(
                "color: #52C41A; font-weight: bold; font-size: %dpx;" % AppSettings().get_font_sizes()[0]
            )
        self.judge_status_label.setVisible(True)
        self._update_nav_buttons()

        # 全部判完自动显示结果
        if self.judged_count >= len(self.questions):
            self._finish_exam()

    def _prev_question(self):
        """切换到上一题：索引减1，重新渲染答题区"""
        if self.current_index > 0:
            self.current_index -= 1
            self._show_current_question()
            self.answer_frame.setFocus()

    def _next_question(self):
        """切换到下一题：索引加1，重新渲染答题区"""
        if self.current_index < len(self.questions) - 1:
            self.current_index += 1
            self._show_current_question()
            self.answer_frame.setFocus()

    def _finish_exam(self):
        """结束考试：统计正确/错误/未答数量及正确率，更新数据库考试记录，展示结果区"""
        correct = sum(1 for v in self.answer_status.values() if v is False)
        wrong = sum(1 for v in self.answer_status.values() if v is True)
        total = correct + wrong

        models.finish_exam(self.current_exam_id, correct, wrong)

        self.answer_frame.setVisible(False)
        self.result_frame.setVisible(True)

        if total > 0:
            rate = correct / total * 100
        else:
            rate = 0

        self.result_stats.setText(
            f"正确：{correct} 题    错误：{wrong} 题    未答：{len(self.questions) - total} 题\n"
            f"正确率：{rate:.1f}%"
        )

        if rate >= 80:
            msg = "表现不错，继续加油！"
        elif rate >= 60:
            msg = "还需努力，多复习错题集！"
        else:
            msg = "建议重点复习错题，巩固知识点！"
        self.result_detail.setText(msg)

    def _reset_exam(self):
        """重置考试状态：隐藏结果区，回到组卷设置界面，恢复默认数量并刷新筛选下拉框"""
        self.result_frame.setVisible(False)
        self.setup_frame.setVisible(True)
        self.num_spin.setValue(self.settings.default_exam_count)
        self._refresh_exam_filters()

    def _clear_layout(self, layout):
        """清空 layout 中所有子控件（用于清理图片轮播）"""
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()

    def on_shown(self):
        """面板切换为可见时调用：重置考试界面到初始状态"""
        self._reset_exam()
        self.update_dynamic_styles()

    def update_dynamic_styles(self):
        """字体缩放后重新应用动态样式"""
        s = AppSettings()
        style = s.build_dynamic_style
        self.result_title.setStyleSheet(
            style("font-size: {font_title}px; font-weight: bold; color: #333333;"))
        self.result_stats.setStyleSheet(
            style("font-size: {font_big}px; color: #333333;"))
        # 更新判断状态标签（如有当前题目的判断结果）
        status = self.answer_status.get(self.current_index)
        if status is True:
            self.judge_status_label.setStyleSheet(
                style("color: #FF4D4F; font-weight: bold; font-size: {font_base}px;"))
        elif status is False:
            self.judge_status_label.setStyleSheet(
                style("color: #52C41A; font-weight: bold; font-size: {font_base}px;"))

"""
错题集面板。

展示所有做错的题目列表，支持按关键词搜索、按分类筛选、查看详情、
标记已掌握（重置错题计数）以及删除题目。

表格列：
  序号 —— 列表序号
  题目摘要 —— 截取题干前60字显示，纯图片题显示"[图片题目]"
  分类 —— 题目所属分类名称
  做错次数 —— 以红色字体居中显示
  掌握 —— "已掌握"按钮，点击重置错题计数
  操作 —— 编辑按钮（跳转题目编辑页）和删除按钮
"""
import os
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QEvent
from PyQt5.QtGui import QFontMetrics
from database import models
from config import AppSettings


class WrongCollectionPanel(QWidget):
    edit_requested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.wrong_questions = []
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)

        title = QLabel("错题集")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # ---- 筛选栏 ----
        # 关键词搜索（实时过滤）+ 分类下拉筛选
        filter_frame = QFrame()
        filter_frame.setObjectName("card")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(16, 10, 16, 10)
        filter_layout.setSpacing(12)

        filter_layout.addWidget(QLabel("搜索："))
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索错题...")
        self.search_input.setMaximumWidth(220)
        self.search_input.textChanged.connect(self._do_search)
        filter_layout.addWidget(self.search_input)

        filter_layout.addWidget(QLabel("分类："))
        self.cat_filter = QComboBox()
        self.cat_filter.currentIndexChanged.connect(self._do_search)
        filter_layout.addWidget(self.cat_filter)

        filter_layout.addStretch()

        layout.addWidget(filter_frame)

        # ---- 统计 ----
        # 显示当前筛选条件下的错题总数
        self.stats_label = QLabel()
        self.stats_label.setObjectName("statusLabel")
        layout.addWidget(self.stats_label)

        # ---- 错题表格 ----
        # 列布局：
        #   [固定-左] 序号(0)
        #   [可动]     题目摘要(1) | 分类(2)
        #   [固定-右]                    做错次数(3) | 掌握(4) | 操作(5)
        self._col_count = 6
        self._locked_widths = {}
        self._movable_cols = ()
        self._movable_ratios = {}

        self.table = QTableWidget()
        self.table.setColumnCount(self._col_count)
        headers = ["序号", "题目摘要", "分类", "做错次数", "掌握", "操作"]
        self.table.setHorizontalHeaderLabels(headers)
        header = self.table.horizontalHeader()
        fm = QFontMetrics(header.font())

        # 固定列宽度
        for c, base in [(0, max(50, fm.width(headers[0]) * 3 // 2)),
                        (3, max(80, fm.width(headers[3]) * 3 // 2)),
                        (4, 100),
                        (5, 200)]:
            self.table.setColumnWidth(c, base)
            self._locked_widths[c] = base
        # 可动列初始宽度
        movable_init = {1: 400,
                        2: max(100, fm.width(headers[2]) * 3 // 2)}
        self._movable_cols = tuple(movable_init.keys())
        self._absorb_col = 1  # 题目摘要 — 拖拽补偿列
        total = sum(movable_init.values())
        self._movable_ratios = {c: w / total for c, w in movable_init.items()}
        for c, w in movable_init.items():
            self.table.setColumnWidth(c, w)

        # 可动列 Interactive，固定列 Fixed
        for i in self._movable_cols:
            header.setSectionResizeMode(i, QHeaderView.Interactive)
        for c in self._locked_widths:
            header.setSectionResizeMode(c, QHeaderView.Fixed)

        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        self.table.viewport().installEventFilter(self)

        self._fill_timer = QTimer()
        self._fill_timer.setSingleShot(True)
        self._fill_timer.timeout.connect(self._after_drag)
        header.sectionResized.connect(self._on_section_resized)

        layout.addWidget(self.table)

    def _do_search(self):
        """根据当前搜索关键词和分类筛选错题数据，并刷新表格。"""
        keyword = self.search_input.text().strip()
        cat_id = self.cat_filter.currentData()

        self.wrong_questions = models.get_wrong_questions(keyword, cat_id)
        self._refresh_table()

    def _refresh_table(self):
        """用 self.wrong_questions 数据重新填充表格并更新统计标签。"""
        self.table.setRowCount(len(self.wrong_questions))
        self.stats_label.setText(f"错题总数：{len(self.wrong_questions)}")

        for i, q in enumerate(self.wrong_questions):
            # 序号列
            self.table.setItem(i, 0, QTableWidgetItem(str(i + 1)))

            # 题目摘要列：截取前60字符，空文本则显示"[图片题目]"
            summary = q["question_text"][:60] + "..." if len(q["question_text"]) > 60 else q["question_text"]
            if not summary:
                summary = "[图片题目]"
            self.table.setItem(i, 1, QTableWidgetItem(summary))

            # 分类列：从筛选下拉框中匹配名称
            cat_name = ""
            if q["category_id"]:
                for j in range(self.cat_filter.count()):
                    if self.cat_filter.itemData(j) == q["category_id"]:
                        cat_name = self.cat_filter.itemText(j)
                        break
            self.table.setItem(i, 2, QTableWidgetItem(cat_name))

            # 做错次数列：红色居中显示
            wrong_item = QTableWidgetItem(str(q["wrong_count"]))
            wrong_item.setTextAlignment(Qt.AlignCenter)
            wrong_item.setForeground(Qt.red)
            self.table.setItem(i, 3, wrong_item)

            # 掌握列："已掌握"按钮，点击后重置错题计数
            mastered_btn = QPushButton("已掌握")
            mastered_btn.setObjectName("smallBtn")
            mastered_btn.clicked.connect(lambda checked, qid=q["id"]: self._mark_mastered(qid))
            self.table.setCellWidget(i, 4, mastered_btn)

            # 操作列：编辑按钮 + 删除按钮
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(6)

            edit_btn = QPushButton("编辑")
            edit_btn.setObjectName("smallBtn")
            edit_btn.clicked.connect(lambda checked, qid=q["id"]: self.edit_requested.emit(qid))
            btn_layout.addWidget(edit_btn)

            del_btn = QPushButton("删除")
            del_btn.setObjectName("dangerBtn")
            del_btn.clicked.connect(lambda checked, qid=q["id"]: self._delete_question(qid))
            btn_layout.addWidget(del_btn)

            self.table.setCellWidget(i, 5, btn_widget)

        self._save_columns()
        QTimer.singleShot(100, self._adjust_columns_delayed)

    def _delete_question(self, qid):
        """弹出确认对话框，确认后从数据库删除该题目并刷新列表。"""
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这道题目吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return
        models.delete_question(qid)
        self._do_search()

    def _mark_mastered(self, qid):
        """弹出确认对话框，确认后将该题目的错题计数重置为零并刷新列表。"""
        reply = QMessageBox.question(
            self, "确认", "确定已掌握此题？将重置错题计数。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            models.reset_wrong_count(qid)
            self._do_search()

    def _show_detail(self, q):
        """以消息框展示单道错题的详细信息，包括题目、答案、备注、错题次数和标签。"""
        detail = f"【题目】\n{q['question_text'] or '[图片]'}\n\n"
        detail += f"【答案】\n{q['answer_text'] or '[图片]'}\n\n"
        if q.get("notes"):
            detail += f"【备注】\n{q['notes']}\n\n"
        detail += f"【做错次数】{q['wrong_count']}"

        tags = models.get_question_tags(q["id"])
        if tags:
            detail += f"\n【标签】{'、'.join(t['name'] for t in tags)}"

        QMessageBox.information(self, "错题详情", detail)

    def _on_cell_double_clicked(self, row, col):
        if row < 0 or row >= len(self.wrong_questions):
            return
        if col == 4 or col == 5:
            return
        self.edit_requested.emit(self.wrong_questions[row]["id"])

    # ── 比例布局系统 ────────────────────────────────────────────────
    def _movable_space(self):
        fixed = sum(self._locked_widths.values())
        return max(0, self.table.viewport().width() - fixed - 2)

    def _snapshot_ratios(self):
        total = sum(self.table.columnWidth(c) for c in self._movable_cols)
        if total > 0:
            self._movable_ratios = {c: self.table.columnWidth(c) / total
                                    for c in self._movable_cols}

    def _apply_layout(self):
        """固定列复位，可动列按比例瓜分剩余空间（末列吸收取整误差）"""
        header = self.table.horizontalHeader()
        if header.count() < self._col_count:
            return
        space = self._movable_space()
        total_r = sum(self._movable_ratios.values())
        if total_r <= 0:
            return
        for c in self._locked_widths:
            if header.sectionSize(c) != self._locked_widths[c]:
                header.resizeSection(c, self._locked_widths[c])
        used = 0
        cols = self._movable_cols
        for c in cols[:-1]:
            w = max(30, int(space * self._movable_ratios[c] / total_r))
            if header.sectionSize(c) != w:
                header.resizeSection(c, w)
            used += w
        w_last = max(30, space - used)
        if header.sectionSize(cols[-1]) != w_last:
            header.resizeSection(cols[-1], w_last)

    # ── 事件处理 ─────────────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_layout()

    def eventFilter(self, obj, event):
        """Shift+滚轮 → 水平滚动"""
        if obj is self.table.viewport() and event.type() == QEvent.Wheel:
            if event.modifiers() & Qt.ShiftModifier:
                bar = self.table.horizontalScrollBar()
                delta = event.angleDelta().y()
                bar.setValue(bar.value() - delta)
                return True
        return super().eventFilter(obj, event)

    def _on_section_resized(self, col, old_size, new_size):
        if old_size != new_size:
            self._fill_timer.start(250)

    def _after_drag(self):
        """拖拽结束：复位锁定列，剩余空间由题目摘要(1)吸收"""
        header = self.table.horizontalHeader()
        for c, w in self._locked_widths.items():
            if header.sectionSize(c) != w:
                header.resizeSection(c, w)
        used = sum(header.sectionSize(i) for i in range(self._col_count) if i != self._absorb_col)
        avail = self.table.viewport().width() - used - 2
        if avail > 30 and header.sectionSize(self._absorb_col) != avail:
            header.resizeSection(self._absorb_col, avail)
        self._snapshot_ratios()

    def on_shown(self):
        self._refresh_filters()
        self._do_search()
        QTimer.singleShot(100, self._adjust_columns_delayed)

    def _adjust_columns_delayed(self):
        self._restore_columns()
        self._apply_layout()

    def _restore_columns(self):
        saved = AppSettings().load_table_columns("wrong_collection")
        if saved and len(saved) == self._col_count:
            ratios = {}
            total = 0
            for c in self._movable_cols:
                if c < len(saved) and saved[c] > 0:
                    ratios[c] = saved[c]
                    total += saved[c]
            if total > 0:
                self._movable_ratios = {c: v / total for c, v in ratios.items()}

    def _save_columns(self):
        widths = [0] * self._col_count
        scale = 10000
        for c, r in self._movable_ratios.items():
            widths[c] = int(r * scale)
        AppSettings().save_table_columns("wrong_collection", widths)

    def _refresh_filters(self):
        self.cat_filter.blockSignals(True)
        self.cat_filter.clear()
        self.cat_filter.addItem("全部分类", None)
        for cat in models.get_all_categories():
            self.cat_filter.addItem(cat["name"], cat["id"])
        self.cat_filter.blockSignals(False)

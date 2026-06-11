"""
题库管理面板 - Question Bank Management Panel

提供题库的表格化浏览与管理功能，包括：
- 关键词搜索、按分类/标签筛选
- 题目表格展示：序号、图片（缩略图/原图）、题目摘要、分类、标签、错题次数、操作按钮
- 分页浏览（每页 PAGE_SIZE 条）
- 右键快捷菜单：查看详情、编辑、重置错题计数、删除
- 双击题目行快速进入编辑
- 表格列宽记忆（通过 AppSettings 持久化）
"""
import os, subprocess
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame,
    QMessageBox, QMenu,
    QFileDialog, QProgressDialog, QApplication, QInputDialog,
    QDialog, QCheckBox, QDialogButtonBox, QColorDialog,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QEvent, QItemSelection
from PyQt5.QtGui import QPixmap, QIcon, QFontMetrics, QKeySequence, QColor
from qfluentwidgets import (
    PrimaryPushButton, PushButton, TransparentPushButton,
    ComboBox, LineEdit, CardWidget,
)
from database import models
from config import AppSettings
from services.export_service import export_questions


PAGE_SIZE = 20
THUMB_SIZE = 50
FULL_IMAGE_WIDTH = 300


class _HighlightHeader(QHeaderView):
    """支持选中高亮的自定义表头：检查对应行/列是否有选中单元格来决定背景色"""
    _table_ref = None

    def paintSection(self, painter, rect, logicalIndex):
        if self._table_ref is not None:
            sel = self._table_ref.selectionModel()
            highlighted = False
            if self.orientation() == Qt.Vertical:
                # 纵向表头：检查该行是否有被选中的单元格
                for c in range(self._table_ref.columnCount()):
                    if sel.isSelected(
                            self._table_ref.model().index(logicalIndex, c)):
                        highlighted = True
                        break
            else:
                # 横向表头：检查该列是否有被选中的单元格
                for r in range(self._table_ref.rowCount()):
                    if sel.isSelected(
                            self._table_ref.model().index(r, logicalIndex)):
                        highlighted = True
                        break
            if highlighted:
                painter.fillRect(rect, QColor("#D2E3FC"))
        super().paintSection(painter, rect, logicalIndex)


class QuestionListPanel(QWidget):
    """题库管理面板：表格视图 + 搜索筛选 + 分页 + CRUD 操作"""

    edit_requested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.all_questions = []    # 当前筛选条件下所有题目
        self.current_page = 0      # 当前页码（0-indexed）
        self._img_labels = []  # (QLabel, file_path, col_index)
        self._dragging = False
        self._auto_scroll_dir = 0
        # 快捷键动作注册表（action_id → handler 函数）
        self._shortcut_actions = {
            "select_all": self._handle_select_all,
            "goto_dialog": self._show_goto_dialog,
            "select_col": self._handle_select_col,
            "select_row": self._handle_select_row,
            "select_region": self._select_current_region,
            "jump_edge_up": lambda: self._jump_to_data_edge('up'),
            "jump_edge_down": lambda: self._jump_to_data_edge('down'),
            "jump_edge_left": lambda: self._jump_to_data_edge('left'),
            "jump_edge_right": lambda: self._jump_to_data_edge('right'),
            "prev_page": self._prev_page,
            "next_page": self._next_page,
            "clear_selection": lambda: self.table.clearSelection(),
        }
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)

        title = QLabel("题库管理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # ---- 搜索和筛选栏 ----
        filter_frame = CardWidget()
        filter_frame.setObjectName("card")
        filter_layout = QHBoxLayout(filter_frame)
        filter_layout.setContentsMargins(16, 10, 16, 10)
        filter_layout.setSpacing(12)

        filter_layout.addWidget(QLabel("搜索："))
        self.search_input = LineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索...")
        self.search_input.setMaximumWidth(220)
        self.search_input.textChanged.connect(self._do_search)
        filter_layout.addWidget(self.search_input)

        filter_layout.addWidget(QLabel("分类："))
        self.cat_filter = ComboBox()
        self.cat_filter.currentIndexChanged.connect(self._do_search)
        self.cat_filter.currentIndexChanged.connect(self._update_cat_btns)
        filter_layout.addWidget(self.cat_filter)

        self.cat_rename_btn = PushButton("重命名")
        self.cat_rename_btn.setObjectName("smallBtn")
        self.cat_rename_btn.setCursor(Qt.PointingHandCursor)
        self.cat_rename_btn.setVisible(False)
        self.cat_rename_btn.clicked.connect(self._rename_category)
        filter_layout.addWidget(self.cat_rename_btn)

        self.cat_del_btn = PushButton("删除")
        self.cat_del_btn.setObjectName("dangerBtn")
        self.cat_del_btn.setCursor(Qt.PointingHandCursor)
        self.cat_del_btn.setVisible(False)
        self.cat_del_btn.clicked.connect(self._delete_category)
        filter_layout.addWidget(self.cat_del_btn)

        filter_layout.addWidget(QLabel("标签："))
        self.tag_filter = ComboBox()
        self.tag_filter.currentIndexChanged.connect(self._do_search)
        filter_layout.addWidget(self.tag_filter)

        filter_layout.addStretch()

        # 排序按钮：点击显示排序菜单
        self.sort_btn = PushButton("排序 ▾")
        self.sort_btn.setObjectName("secondaryBtn")
        self.sort_btn.setCursor(Qt.PointingHandCursor)
        self.sort_btn.clicked.connect(
            lambda: self._show_sort_menu(
                self.sort_btn.mapToGlobal(self.sort_btn.rect().bottomLeft())))
        filter_layout.addWidget(self.sort_btn)

        self.batch_btn = PushButton("选择操作 ▾")
        self.batch_btn.setObjectName("primaryBtn")
        self.batch_btn.setCursor(Qt.PointingHandCursor)
        self._batch_menu = QMenu(self)
        self._batch_menu.addAction("导出题库", self._export_questions)
        self._batch_menu.addAction("添加标签", self._batch_add_tags)
        self._batch_menu.addAction("添加到新分类", self._batch_move_category)
        self.batch_btn.clicked.connect(
            lambda: self._batch_menu.exec_(
                self.batch_btn.mapToGlobal(self.batch_btn.rect().bottomLeft())))
        filter_layout.addWidget(self.batch_btn)

        layout.addWidget(filter_frame)

        # ---- 统计 + 翻页 ----
        top_bar = QHBoxLayout()
        self.col_filter_btn = PushButton("列表筛选器 ▾")
        self.col_filter_btn.setObjectName("smallBtn")
        self.col_filter_btn.setCursor(Qt.PointingHandCursor)
        top_bar.addWidget(self.col_filter_btn)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("statusLabel")
        top_bar.addWidget(self.stats_label)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # ---- 题目表格 ----
        # 列布局 (10列)：
        #   [固定-左] 序号(0) | 初始编号(1)
        #   [可动]     星标(2) | 题目(3) | 分类(4) | 标签(5) | 答案(6) | 错次(7)
        #   [固定-右]                            最近修改(8) | 操作(9)
        self._col_count = 11
        self._locked_widths = {}
        self._movable_cols = ()
        self._movable_ratios = {}
        self._sort_col = -1       # 当前排序列 (-1=默认/恢复原状)
        self._sort_state = 0      # 0=原序, 1=升序, 2=降序
        self._original_order = [] # 保存初始顺序用于恢复

        self.table = QTableWidget()
        self.table.setVerticalHeader(_HighlightHeader(Qt.Vertical))
        self.table.setHorizontalHeader(_HighlightHeader(Qt.Horizontal))
        self.table.verticalHeader()._table_ref = self.table
        self.table.horizontalHeader()._table_ref = self.table
        self.table.setColumnCount(self._col_count)
        self._all_headers = ["序号", "初始编号", "星标", "题目", "分类",
                             "标签", "答案", "备注", "错次", "最近修改", "操作"]
        self.table.setHorizontalHeaderLabels(self._all_headers)
        header = self.table.horizontalHeader()
        fm = QFontMetrics(header.font())

        for c, base in [(0, max(100, fm.width(self._all_headers[0]) * 3 // 2)),
                        (10, 180)]:
            self.table.setColumnWidth(c, base)
            self._locked_widths[c] = base
        movable_init = {1: 140,
                        2: 60,
                        3: 500,
                        4: max(100, fm.width(self._all_headers[4]) * 3 // 2),
                        5: max(150, fm.width(self._all_headers[5]) * 3 // 2),
                        6: 200,
                        7: 120,
                        8: max(80, fm.width(self._all_headers[8]) * 3 // 2),
                        9: 140}
        self._movable_cols = tuple(movable_init.keys())
        self._absorb_col = 3  # 题目列
        total = sum(movable_init.values())
        self._movable_ratios = {c: w / total for c, w in movable_init.items()}
        for c, w in movable_init.items():
            self.table.setColumnWidth(c, w)

        for i in self._movable_cols:
            header.setSectionResizeMode(i, QHeaderView.Interactive)
        for c in self._locked_widths:
            header.setSectionResizeMode(c, QHeaderView.Fixed)

        # 默认隐藏初始编号和备注列
        self.table.setColumnHidden(1, True)
        self.table.setColumnHidden(7, True)

        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAutoScroll(False)  # 关闭默认自动滚动，用自定义速度
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._auto_scroll_timer = QTimer()
        self._auto_scroll_timer.timeout.connect(self._do_auto_scroll)
        # Qt 选择模型变化 → 更新选中计数
        self.table.selectionModel().selectionChanged.connect(
            self._update_selection_status)
        # 行号表头（Excel 风）
        self.table.verticalHeader().setVisible(True)
        self.table.verticalHeader().setSectionsClickable(True)
        self.table.verticalHeader().sectionClicked.connect(self._on_row_header_clicked)
        # 左上角全选按钮
        from PyQt5.QtWidgets import QAbstractButton
        corner = self.table.findChild(QAbstractButton)
        if corner:
            corner.clicked.connect(self._on_corner_clicked)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        # 列头点击 → 选择整列；右键 → 排序
        header.sectionClicked.connect(self._on_header_clicked)
        header.setContextMenuPolicy(Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(self._on_header_context_menu)
        self.table.cellPressed.connect(self._on_cell_pressed)   # 鼠标按下→记录起始行(拖拽用)
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)
        self._last_clicked_row = -1
        self._drag_active = False

        layout.addWidget(self.table)

        # 列表筛选器菜单（按钮在 filter bar 中，菜单在此初始化）
        self._col_menu = QMenu(self)
        for c in range(self._col_count):
            if c in (0, 10):
                continue
            action = self._col_menu.addAction(self._all_headers[c])
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(c))
            action.setData(c)
            action.toggled.connect(
                lambda checked, col=c: self.table.setColumnHidden(col, not checked))
        self.col_filter_btn.clicked.connect(
            lambda: self._col_menu.exec_(
                self.col_filter_btn.mapToGlobal(self.col_filter_btn.rect().bottomLeft())))

        # ---- 翻页控件 ----
        page_frame = CardWidget()
        page_frame.setObjectName("card")
        page_layout = QHBoxLayout(page_frame)
        page_layout.setContentsMargins(12, 8, 12, 8)
        page_layout.setSpacing(10)

        self.prev_btn = PushButton("◀ 上一页")
        self.prev_btn.setObjectName("smallBtn")
        self.prev_btn.clicked.connect(self._prev_page)
        page_layout.addWidget(self.prev_btn)

        page_layout.addStretch()

        self.page_label = QLabel()
        self.page_label.setObjectName("statusLabel")
        page_layout.addWidget(self.page_label)

        page_layout.addStretch()

        self.next_btn = PushButton("下一页 ▶")
        self.next_btn.setObjectName("smallBtn")
        self.next_btn.clicked.connect(self._next_page)
        page_layout.addWidget(self.next_btn)

        layout.addWidget(page_frame)

    @property
    def _selected_ids(self):
        """计算属性：从 Qt 选择模型中动态获取被选中题目 ID 集合"""
        result = set()
        sel_model = self.table.selectionModel()
        if sel_model is None:
            return result
        rows_seen = set()
        for idx in sel_model.selectedIndexes():
            r = idx.row()
            if r not in rows_seen:
                rows_seen.add(r)
                q = self._get_question_at_row(r)
                if q:
                    result.add(q["id"])
        return result

    def _total_pages(self):
        """根据当前题目总数和 PAGE_SIZE 计算总页数（至少1页）"""
        return max(1, (len(self.all_questions) + PAGE_SIZE - 1) // PAGE_SIZE)

    def _do_search(self):
        """执行搜索：支持普通分类、星标收藏夹(-1)、错题集(-2)"""
        # 刷新期间不响应
        if getattr(self, '_refreshing', False):
            return
        try:
            keyword = self.search_input.text().strip()
            cat_id = self.cat_filter.currentData()
            tag_id = self.tag_filter.currentData()
        except Exception:
            return

        # 保护：若当前为禁用的分隔符项，跳过
        if cat_id is None:
            idx = self.cat_filter.currentIndex()
            if 0 <= idx < len(self.cat_filter.items):
                try:
                    if not self.cat_filter.items[idx].isEnabled():
                        return
                except Exception:
                    pass

        try:
            if cat_id == -1:
                self.all_questions = models.get_starred_questions(keyword, None)
            elif cat_id == -2:
                self.all_questions = models.get_wrong_questions(keyword, None)
            else:
                self.all_questions = models.search_questions(keyword, cat_id, tag_id)
        except Exception:
            self.all_questions = []
        # 附加 _tags_str 用于排序
        for q in self.all_questions:
            tags = models.get_question_tags(q["id"])
            q["_tags_str"] = ", ".join(t["name"] for t in tags)
        # 保存原始顺序 + 保存 sort 状态
        self._original_order = self.all_questions[:]
        if self._sort_col >= 0 and self._sort_state > 0:
            self._apply_sort()
        else:
            self.current_page = 0
            self._refresh_table()

    def _refresh_table(self):
        """根据 self.all_questions 和当前页码渲染表格数据"""
        total = len(self.all_questions)
        total_pages = self._total_pages()

        if self.current_page >= total_pages:
            self.current_page = total_pages - 1

        start = self.current_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_items = self.all_questions[start:end]

        # 备份当前页选中 ID（setRowCount 会清除 Qt 的选择模型）
        saved_ids = self._selected_ids.copy()
        self.table.setRowCount(len(page_items))   # 设定行数，触发 Qt 清空旧选择
        self.stats_label.setText(f"共 {total} 道题目")

        base_index = start
        self._img_labels.clear()

        for i, q in enumerate(page_items):
            images = models.get_question_images(q["id"])
            q_images = [img for img in images if img["image_type"] == "question"]
            a_images = [img for img in images if img["image_type"] == "answer"]
            mode = AppSettings().image_display_mode

            # 第0列：序号
            idx_item = QTableWidgetItem(str(base_index + i + 1))
            idx_item.setTextAlignment(Qt.AlignCenter)
            idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsUserCheckable)
            self.table.setItem(i, 0, idx_item)

            # 第1列：初始编号
            uid = q.get("uid", "")
            uid_item = QTableWidgetItem(uid if uid else "-")
            uid_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 1, uid_item)

            # 第2列：星标
            is_starred = bool(q.get("starred", 0))
            star_btn = PushButton("★" if is_starred else "☆")
            star_btn.setFixedSize(40, 40)
            star_btn.setCursor(Qt.PointingHandCursor)
            if is_starred:
                star_btn.setStyleSheet(
                    "QPushButton { border: 1px solid #F5A623; border-radius: 20px;"
                    " font-size: 22px; color: #F5A623; background: #FFF8E1; }"
                    "QPushButton:hover { background: #F5A623; color: #FFF; }")
            else:
                star_btn.setStyleSheet(
                    "QPushButton { border: 1px solid #DDD; border-radius: 20px;"
                    " font-size: 22px; color: #BBB; background: #FAFAFA; }"
                    "QPushButton:hover { border-color: #F5A623; color: #F5A623;"
                    " background: #FFF8E1; }")
            star_btn.clicked.connect(lambda checked, qid=q["id"], sb=star_btn:
                                     self._toggle_star(qid, sb))
            self.table.setCellWidget(i, 2, star_btn)

            # 第3列：题目（图片 + 文字）
            q_widget = QWidget()
            q_layout = QVBoxLayout(q_widget)
            q_layout.setContentsMargins(4, 2, 4, 2)
            q_layout.setSpacing(4)

            if q_images and os.path.exists(q_images[0]["image_path"]):
                pixmap = QPixmap(q_images[0]["image_path"])
                col_w = self.table.columnWidth(1) - 12
                if mode == "full":
                    if pixmap.width() > col_w:
                        pixmap = pixmap.scaledToWidth(col_w, Qt.SmoothTransformation)
                else:
                    pixmap = pixmap.scaled(THUMB_SIZE, THUMB_SIZE,
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
                q_img = QLabel()
                q_img.setPixmap(pixmap)
                q_img.setAlignment(Qt.AlignCenter)
                q_layout.addWidget(q_img)
                self._img_labels.append((q_img, q_images[0]["image_path"], 3))

            q_text = q["question_text"] if q["question_text"] else ""
            q_label = QLabel(q_text)
            q_label.setWordWrap(True)
            q_layout.addWidget(q_label)
            self.table.setCellWidget(i, 3, q_widget)

            # 第4列：分类
            cat_name = ""
            if q["category_id"]:
                for j in range(self.cat_filter.count()):
                    if self.cat_filter.itemData(j) == q["category_id"]:
                        cat_name = self.cat_filter.itemText(j)
                        break
            self.table.setItem(i, 4, QTableWidgetItem(cat_name))

            # 第5列：标签（彩色徽章，点击编辑）
            tags = models.get_question_tags(q["id"])
            tag_widget = QWidget()
            tag_layout = QHBoxLayout(tag_widget)
            tag_layout.setContentsMargins(2, 2, 2, 2)
            tag_layout.setSpacing(4)
            for t in tags:
                chip = QLabel(t["name"])
                chip.setStyleSheet(
                    f"background-color: {t.get('color', '#4A90D9')};"
                    f" color: #FFFFFF; border-radius: 10px;"
                    f" padding: 4px 10px; font-size: 13px; font-weight: bold;")
                chip.setFixedHeight(26)
                chip.setCursor(Qt.PointingHandCursor)
                tid = t["id"]
                chip.mousePressEvent = lambda e, tid=tid: self._edit_tag_dialog(tid)
                tag_layout.addWidget(chip)
            tag_layout.addStretch()
            self.table.setCellWidget(i, 5, tag_widget)

            # 第6列：答案（点击按钮切换显示/隐藏）
            ans_widget = QWidget()
            ans_layout = QVBoxLayout(ans_widget)
            ans_layout.setContentsMargins(4, 2, 4, 2)
            ans_layout.setSpacing(4)

            # 答案内容（初始隐藏）
            ans_content = QWidget()
            ans_inner = QVBoxLayout(ans_content)
            ans_inner.setContentsMargins(0, 0, 0, 0)
            ans_inner.setSpacing(4)

            if a_images and os.path.exists(a_images[0]["image_path"]):
                pixmap = QPixmap(a_images[0]["image_path"])
                col_w = self.table.columnWidth(5) - 12
                if mode == "full":
                    if pixmap.width() > col_w:
                        pixmap = pixmap.scaledToWidth(col_w, Qt.SmoothTransformation)
                else:
                    pixmap = pixmap.scaled(THUMB_SIZE, THUMB_SIZE,
                                           Qt.KeepAspectRatio, Qt.SmoothTransformation)
                a_img = QLabel()
                a_img.setPixmap(pixmap)
                a_img.setAlignment(Qt.AlignCenter)
                ans_inner.addWidget(a_img)
                self._img_labels.append((a_img, a_images[0]["image_path"], 6))

            a_text = q["answer_text"] if q["answer_text"] else ""
            a_label = QLabel(a_text)
            a_label.setWordWrap(True)
            ans_inner.addWidget(a_label)
            ans_content.setVisible(False)
            ans_layout.addWidget(ans_content)

            # 切换按钮
            toggle_btn = PushButton("点击查看答案")
            toggle_btn.setStyleSheet(
                "QPushButton { background-color: #D0D0D0; color: #666666;"
                " border: none; border-radius: 4px; font-size: 14px; }"
                "QPushButton:hover { background-color: #C0C0C0; }")
            toggle_btn.setCursor(Qt.PointingHandCursor)
            ans_layout.addWidget(toggle_btn)

            toggle_btn.clicked.connect(
                lambda checked, ac=ans_content, tb=toggle_btn, r=i:
                (ac.setVisible(not ac.isVisible()),
                 tb.setText("点击隐藏答案" if ac.isVisible() else "点击查看答案"),
                 self.table.resizeRowToContents(r)))

            # 点击答案内容任意处 → 隐藏；点击 cell 任意处（答案隐藏时）→ 显示
            def _toggle_ans(e, ac=ans_content, tb=toggle_btn, r=i):
                visible = not ac.isVisible()
                ac.setVisible(visible)
                tb.setText("点击隐藏答案" if visible else "点击查看答案")
                self.table.resizeRowToContents(r)

            for child in ans_content.findChildren(QWidget) + [ans_content]:
                child.setCursor(Qt.PointingHandCursor)
                child.mousePressEvent = _toggle_ans
            ans_widget.mousePressEvent = _toggle_ans
            ans_widget.setCursor(Qt.PointingHandCursor)

            self.table.setCellWidget(i, 6, ans_widget)

            # 第7列：备注
            notes_text = q.get("notes", "")
            notes_item = QTableWidgetItem(notes_text if notes_text else "")
            self.table.setItem(i, 7, notes_item)

            # 第8列：错题次数
            wrong_item = QTableWidgetItem(str(q["wrong_count"]))
            wrong_item.setTextAlignment(Qt.AlignCenter)
            if q["wrong_count"] > 0:
                wrong_item.setForeground(Qt.red)
            self.table.setItem(i, 8, wrong_item)

            # 第9列：最近修改日期
            updated = q.get("updated_at", "")
            if updated and len(updated) > 16:
                updated = updated[:10].replace("-", "/") + " " + updated[11:19]
            date_item = QTableWidgetItem(updated if updated else "-")
            date_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 9, date_item)

            # 第10列：操作按钮（编辑 / 删除）
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(4, 2, 4, 2)
            btn_layout.setSpacing(6)

            edit_btn = PushButton("编辑")
            edit_btn.setObjectName("smallBtn")
            edit_btn.clicked.connect(lambda checked, qid=q["id"]: self.edit_requested.emit(qid))
            btn_layout.addWidget(edit_btn)

            del_btn = PushButton("删除")
            del_btn.setObjectName("dangerBtn")
            del_btn.clicked.connect(lambda checked, qid=q["id"]: self._delete_question(qid))
            btn_layout.addWidget(del_btn)

            self.table.setCellWidget(i, 10, btn_widget)

        # 翻页后恢复选择高亮：若题目 ID 在之前保存的集合中，则选中该行所有单元格
        if saved_ids:
            for r in range(len(page_items)):
                q2 = self._get_question_at_row(r)
                if q2 and q2["id"] in saved_ids:
                    for c in range(self._col_count):
                        self.table.selectionModel().select(
                            self.table.model().index(r, c),
                            self.table.selectionModel().Select)

        self.page_label.setText(f"第 {self.current_page + 1} / {total_pages} 页")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)

        self.table.resizeRowsToContents()
        self._save_columns()
        QTimer.singleShot(100, self._adjust_columns_delayed)

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._refresh_table()

    def _next_page(self):
        if self.current_page < self._total_pages() - 1:
            self.current_page += 1
            self._refresh_table()

    def _get_question_at_row(self, row):
        """根据表格行号反查 all_questions 中对应题目数据"""
        idx = self.current_page * PAGE_SIZE + row
        if 0 <= idx < len(self.all_questions):
            return self.all_questions[idx]
        return None

    def _delete_question(self, qid):
        """删除指定题目：弹出确认对话框，确认后删除关联图片文件并清除数据库记录，随后刷新列表"""
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这道题目吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply != QMessageBox.Yes:
            return

        images = models.get_question_images(qid)
        for img in images:
            if os.path.exists(img["image_path"]):
                os.remove(img["image_path"])

        models.delete_question(qid)
        self._do_search()

    # ── 排序系统 ─────────────────────────────────────────────────────
    _SORT_KEYS = {
        1: lambda q: q.get("uid", ""),
        2: lambda q: q.get("starred", 0),
        3: lambda q: q.get("question_text", ""),
        4: lambda q: q.get("category_id") or 0,
        5: lambda q: q.get("_tags_str", ""),
        6: lambda q: q.get("answer_text", ""),
        7: lambda q: q.get("notes", ""),
        8: lambda q: q.get("wrong_count", 0),
        9: lambda q: q.get("updated_at", ""),
    }

    def _on_header_clicked(self, col):
        """列头点击 = 选中整列（需求#5）。
        Ctrl+点击 = 追加列（需求#8）；Shift+点击 = 连续列（需求#9）。"""
        modifiers = QApplication.keyboardModifiers()
        sel = self.table.selectionModel()
        if modifiers & Qt.ControlModifier:
            # Ctrl+点击：追加该列到已有选择
            for r in range(self.table.rowCount()):
                sel.select(self.table.model().index(r, col), sel.Select)
        elif modifiers & Qt.ShiftModifier:
            # Shift+点击：选择从当前列到点击列之间的所有列
            self.table.selectColumn(col)
        else:
            # 普通点击：只选该列
            self.table.clearSelection()
            self.table.selectColumn(col)

    def _on_header_context_menu(self, pos):
        """列头右键菜单 → 排序操作"""
        col = self.table.horizontalHeader().logicalIndexAt(pos)
        if col not in self._SORT_KEYS:
            return
        menu = QMenu(self)
        menu.addAction("↑ 升序排列", lambda: self._set_sort(col, 1))
        menu.addAction("↓ 降序排列", lambda: self._set_sort(col, 2))
        menu.addAction("— 恢复默认顺序", lambda: self._set_sort(-1, 0))
        menu.exec_(self.table.horizontalHeader().viewport().mapToGlobal(pos))

    def _set_sort(self, col, state):
        """直接设置排序列和状态"""
        if state == 0:
            self._sort_col = -1
            self._sort_state = 0
            self.sort_btn.setText("排序 ▾")
        else:
            self._sort_col = col
            self._sort_state = state
            arrow = " ↑" if state == 1 else " ↓"
            header_label = self._all_headers[col]
            self.sort_btn.setText(f"排序: {header_label}{arrow}")
        self._apply_sort()

    def _show_sort_menu(self, global_pos):
        """排序按钮点击 → 显示排序菜单"""
        menu = QMenu(self)
        menu.addAction("— 恢复默认顺序", lambda: self._set_sort(-1, 0))
        menu.addSeparator()
        for col, header in enumerate(self._all_headers):
            if col in self._SORT_KEYS:
                menu.addAction(f"↑ {header} 升序", lambda c=col: self._set_sort(c, 1))
                menu.addAction(f"↓ {header} 降序", lambda c=col: self._set_sort(c, 2))
        menu.exec_(global_pos)

    def _apply_sort(self):
        header = self.table.horizontalHeader()
        if self._sort_state == 0:
            # 恢复原始顺序
            if self._original_order:
                self.all_questions = self._original_order[:]
            header.setSortIndicatorShown(False)
            self._sort_col = -1
        else:
            key = self._SORT_KEYS.get(self._sort_col)
            if key:
                reverse = (self._sort_state == 2)
                self.all_questions.sort(key=key, reverse=reverse)
            header.setSortIndicator(
                self._sort_col,
                Qt.AscendingOrder if self._sort_state == 1 else Qt.DescendingOrder)
            header.setSortIndicatorShown(True)
        self.current_page = 0
        self._refresh_table()

    def keyPressEvent(self, event):
        """键盘事件 → 快捷键分发引擎"""
        key_seq = self._parse_key_event(event)
        if key_seq is None:
            super().keyPressEvent(event)
            return

        # 遍历注册的快捷键，匹配则执行
        settings = AppSettings()
        for action_id, handler in self._shortcut_actions.items():
            if settings.get_shortcut(action_id) == key_seq:
                handler()
                return

        # 扩展到 Qt 原生处理（Shift+Arrow 等）
        super().keyPressEvent(event)

    def _update_selection_status(self):
        """选择变化时更新底部统计标签 + 高亮行列表头"""
        count = len(self._selected_ids)
        total = len(self.all_questions)
        if count:
            self.stats_label.setText(f"共 {total} 道题目 | 已选中 {count} 道")
        else:
            self.stats_label.setText(f"共 {total} 道题目")
        self.table.verticalHeader().viewport().update()
        self.table.horizontalHeader().viewport().update()

    def _on_cell_pressed(self, row, col):
        """鼠标按下 → 记录起始行号；Ctrl+单击 widget 单元格时手动切换选择"""
        self._drag_start_row = row
        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ControlModifier:
            # widget 单元格（星标/标签/答案等）点击被 widget 消费，Qt 不会处理选择
            # 只有 widget 单元格需要手动切换；QTableWidgetItem 单元格由 Qt ExtendedSelection 原生处理
            if self.table.cellWidget(row, col) is not None:
                idx = self.table.model().index(row, col)
                sel = self.table.selectionModel()
                if sel.isSelected(idx):
                    sel.select(idx, sel.Deselect)
                else:
                    sel.select(idx, sel.Select)

    def _toggle_star(self, qid, btn):
        """切换星标状态"""
        new_val = models.toggle_star(qid)
        if new_val:
            btn.setText("★")
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #F5A623; border-radius: 20px;"
                " font-size: 22px; color: #F5A623; background: #FFF8E1; }"
                "QPushButton:hover { background: #F5A623; color: #FFF; }")
        else:
            btn.setText("☆")
            btn.setStyleSheet(
                "QPushButton { border: 1px solid #DDD; border-radius: 20px;"
                " font-size: 22px; color: #BBB; background: #FAFAFA; }"
                "QPushButton:hover { border-color: #F5A623; color: #F5A623;"
                " background: #FFF8E1; }")
        # 同步更新 all_questions 中的状态
        for q in self.all_questions:
            if q["id"] == qid:
                q["starred"] = new_val
                break

    def _get_selected_or_all(self):
        """批量操作的题目来源：有选中→仅返回选中的题目；无选中→返回全部筛选结果"""
        selected = self._selected_ids
        if selected:
            return [q for q in self.all_questions if q["id"] in selected]
        return self.all_questions

    def _batch_move_category(self):
        """批量为选中题目创建新分类并移入"""
        to_edit = self._get_selected_or_all()
        if not to_edit:
            QMessageBox.warning(self, "提示", "未选中任何题目。")
            return
        name, ok = QInputDialog.getText(self, "新建分类", "请输入新分类名称：")
        if not ok or not name.strip():
            return
        success, msg = models.add_category(name.strip())
        if not success:
            QMessageBox.warning(self, "错误", msg)
            return
        # 查找新建分类的 ID
        all_cats = models.get_all_categories()
        new_id = None
        for c in all_cats:
            if c["name"] == name.strip():
                new_id = c["id"]
                break
        if new_id is None:
            return
        models.batch_set_category([q["id"] for q in to_edit], new_id)
        QMessageBox.information(
            self, "完成",
            f"已创建分类「{name.strip()}」并将 {len(to_edit)} 道题目移入。")
        self._refresh_filters()
        self._do_search()

    def _batch_add_tags(self):
        """批量为选中题目添加标签"""
        to_edit = self._get_selected_or_all()
        if not to_edit:
            QMessageBox.warning(self, "提示", "未选中任何题目。")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("添加标签")
        dlg.setMinimumSize(360, 300)
        layout = QVBoxLayout(dlg)

        layout.addWidget(QLabel("选择要添加的标签（可多选）："))
        all_tags = models.get_all_tags()
        checks = []
        for tag in all_tags:
            cb = QCheckBox(tag["name"])
            cb.setStyleSheet(
                f"QCheckBox {{ color: {tag.get('color', '#4A90D9')};"
                f" font-weight: bold; font-size: 14px; spacing: 6px; }}")
            cb._tag_id = tag["id"]
            checks.append(cb)
            layout.addWidget(cb)

        layout.addWidget(QLabel("—— 或创建新标签 ——"))
        row = QHBoxLayout()
        row.addWidget(QLabel("名称:"))
        name_edit = LineEdit()
        name_edit.setPlaceholderText("新标签名称")
        row.addWidget(name_edit)
        row.addWidget(QLabel("颜色:"))
        color_btn = PushButton()
        color_btn.setFixedSize(28, 28)
        color_btn.setStyleSheet(
            "background-color: #4A90D9; border: 1px solid #999; border-radius: 4px;")
        color_btn.setCursor(Qt.PointingHandCursor)
        new_color = ['#4A90D9']

        presets = [
            '#E74C3C', '#E67E22', '#F1C40F', '#2ECC71', '#1ABC9C',
            '#3498DB', '#9B59B6', '#E91E63', '#795548', '#95A5A6',
        ]
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("预设:"))
        preset_row.setSpacing(4)
        for pc in presets:
            pb = PushButton()
            pb.setFixedSize(24, 24)
            pb.setCursor(Qt.PointingHandCursor)
            pb.setStyleSheet(
                f"background-color: {pc}; border: 1px solid #999;"
                f" border-radius: 12px;")
            pb.clicked.connect(
                lambda checked, c=pc, cb=color_btn, nc=new_color:
                nc.__setitem__(0, c) or cb.setStyleSheet(
                    f"background-color: {c}; border: 1px solid #999;"
                    f" border-radius: 4px;"))
            preset_row.addWidget(pb)
        layout.addLayout(preset_row)

        def pick_color():
            c = QColorDialog.getColor()
            if c.isValid():
                new_color[0] = c.name()
                color_btn.setStyleSheet(
                    f"background-color: {c.name()}; border: 1px solid #999;"
                    f" border-radius: 4px;")
        color_btn.clicked.connect(pick_color)
        row.addWidget(color_btn)
        layout.addLayout(row)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        if dlg.exec_() != QDialog.Accepted:
            return

        tag_ids = [cb._tag_id for cb in checks if cb.isChecked()]
        new_name = name_edit.text().strip()
        if new_name:
            tid, err = models.add_tag(new_name, new_color[0])
            if tid:
                tag_ids.append(tid)
            elif err and "UNIQUE" not in err.upper():
                all_t = models.get_all_tags()
                for t in all_t:
                    if t["name"] == new_name:
                        tag_ids.append(t["id"])
                        break

        if not tag_ids:
            return
        qids = [q["id"] for q in to_edit]
        models.batch_set_tags(qids, tag_ids)
        QMessageBox.information(self, "完成", f"已为 {len(qids)} 道题目添加标签。")
        self._do_search()

    def _export_questions(self):
        """导出题目为 HTML 文件夹（有选中则仅导出选中，无选中则导出全部）"""
        to_export = self._get_selected_or_all()

        if not to_export:
            QMessageBox.warning(self, "提示", "当前没有题目可导出。")
            return

        parent_dir = QFileDialog.getExistingDirectory(self, "选择导出位置")
        if not parent_dir:
            return

        total = len(to_export)
        label = f"已选中 {total} 道" if self._selected_ids else f"当前筛选共 {total} 道"
        reply = QMessageBox.question(
            self, "确认导出",
            f"将导出 {label} 题目。\n"
            f"导出格式为包含 index.html 和图片的文件夹。\n确认继续？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return

        progress = QProgressDialog("正在准备导出...", "取消", 0, 100, self)
        progress.setWindowTitle("导出题库")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        QApplication.processEvents()

        cancelled = [False]

        def on_progress(step, cur, total):
            if progress.wasCanceled():
                cancelled[0] = True
                return True
            label = f"{step} ({cur}/{total})" if total != "1" else step
            progress.setLabelText(label)
            try:
                ci, ct = int(cur), int(total)
                if step == "copying":
                    pct = int(10 + 80 * ci / max(ct, 1))
                elif step.startswith("生成"):
                    pct = 95
                else:
                    pct = min(5, int(5 * ci / max(ct, 1)))
                progress.setValue(pct)
            except ValueError:
                pass
            QApplication.processEvents()
            return False

        try:
            success, result = export_questions(
                to_export, parent_dir, on_progress)
        except Exception as e:
            progress.close()
            QMessageBox.critical(self, "导出失败", f"导出过程中发生错误：\n{str(e)}")
            return

        progress.setValue(100)
        progress.close()

        if cancelled[0]:
            QMessageBox.information(self, "已取消", "导出已取消。")
        elif success:
            msg = QMessageBox(self)
            msg.setWindowTitle("导出成功")
            msg.setText(f"已导出 {total} 道题目。")
            msg.setInformativeText(f"位置：{result}")
            open_btn = msg.addButton("打开文件夹", QMessageBox.AcceptRole)
            msg.addButton("关闭", QMessageBox.RejectRole)
            msg.exec_()
            if msg.clickedButton() == open_btn:
                subprocess.Popen(f'explorer "{result}"')
        else:
            QMessageBox.critical(self, "导出失败", str(result))

    def _show_context_menu(self, pos):
        """右键菜单：查看详情、编辑、重置错题计数、删除"""
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        q = self._get_question_at_row(row)
        if q is None:
            return

        menu = QMenu(self)
        view_action = menu.addAction("查看详情")
        edit_action = menu.addAction("编辑")
        reset_action = menu.addAction("重置错题计数")
        menu.addSeparator()
        del_action = menu.addAction("删除")

        action = menu.exec_(self.table.viewport().mapToGlobal(pos))

        if action == edit_action:
            self.edit_requested.emit(q["id"])
        elif action == del_action:
            self._delete_question(q["id"])
        elif action == reset_action:
            models.reset_wrong_count(q["id"])
            self._do_search()
        elif action == view_action:
            self._show_detail(q)

    def _show_detail(self, q):
        """以 QMessageBox 弹出题目详情：题目文本/答案/备注/标签/错题次数"""
        detail = f"【题目】\n{q['question_text'] or '[图片]'}\n\n"
        detail += f"【答案】\n{q['answer_text'] or '[图片]'}\n\n"
        if q.get("notes"):
            detail += f"【备注】\n{q['notes']}\n\n"

        tags = models.get_question_tags(q["id"])
        if tags:
            detail += f"【标签】{'、'.join(t['name'] for t in tags)}\n\n"

        detail += f"【做错次数】{q['wrong_count']}"

        QMessageBox.information(self, "题目详情", detail)

    def _on_cell_double_clicked(self, row, col):
        """双击不再进入编辑模式"""
        pass

    # ── 比例布局系统 ────────────────────────────────────────────────
    def _movable_space(self):
        """可动列可用的总像素"""
        fixed = sum(self._locked_widths.values())
        return max(0, self.table.viewport().width() - fixed - 2)

    def _snapshot_ratios(self):
        """从当前列宽反算比例"""
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
        self._rescale_images()
        self.table.resizeRowsToContents()

    def eventFilter(self, obj, event):
        """Shift+滚轮横向滚动；拖拽自动滚动"""
        if obj is self.table:
            if event.type() == QEvent.KeyPress:
                # 所有键盘事件交给 keyPressEvent 处理
                return False
        if obj is self.table.viewport():
            if event.type() == QEvent.MouseButtonRelease:
                self._auto_scroll_timer.stop()
                self._dragging = False
            elif event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ShiftModifier:
                    bar = self.table.horizontalScrollBar()
                    delta = event.angleDelta().y()
                    bar.setValue(bar.value() - delta)
                    return True
            elif event.type() == QEvent.MouseMove:
                if event.buttons() & Qt.LeftButton:           # 左键按下+鼠标移动 = 拖拽
                    self._dragging = True
                    vp_h = self.table.viewport().height()
                    edge = 30
                    py = event.pos().y()
                    if py > vp_h - edge:
                        self._auto_scroll_dir = 1
                        self._auto_scroll_timer.start(50)
                    elif 0 <= py < edge:
                        self._auto_scroll_dir = -1
                        self._auto_scroll_timer.start(50)
                    else:
                        self._auto_scroll_timer.stop()
                    return False
                else:
                    self._auto_scroll_timer.stop()
            elif event.type() == QEvent.Leave:
                self._auto_scroll_timer.stop()
        return super().eventFilter(obj, event)

    # ── 快捷键引擎 ─────────────────────────────────────────────────
    def _parse_key_event(self, event):
        """将 QKeyEvent 转换为 'Ctrl+A' 格式的快捷键字符串"""
        parts = []
        if event.modifiers() & Qt.ControlModifier:
            parts.append("Ctrl")
        if event.modifiers() & Qt.ShiftModifier:
            parts.append("Shift")
        if event.modifiers() & Qt.AltModifier:
            parts.append("Alt")

        key = event.key()
        # 跳过纯修饰键
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return None

        key_name = QKeySequence(key).toString()
        if key_name:
            parts.append(key_name)
        return "+".join(parts) if parts else key_name

    # ── 选择操作方法 ────────────────────────────────────────────────

    def _handle_select_all(self):
        """Ctrl+A：全选当前页所有单元格"""
        self.table.selectAll()

    def _handle_select_col(self):
        """Ctrl+Space：选中当前单元格所在整列"""
        cur = self.table.currentIndex()
        if cur.isValid():
            self.table.selectColumn(cur.column())

    def _handle_select_row(self):
        """Shift+Space：选中当前单元格所在整行"""
        cur = self.table.currentIndex()
        if cur.isValid():
            self.table.selectRow(cur.row())

    def _select_current_region(self):
        """Ctrl+Shift+Space：选中当前数据区域（连续非空矩形块）"""
        cur = self.table.currentIndex()
        if not cur.isValid():
            return
        r0, c0 = cur.row(), cur.column()
        rc = self.table.rowCount()
        cc = self.table.columnCount()

        def _is_filled(r, c):
            item = self.table.item(r, c)
            widget = self.table.cellWidget(r, c)
            return (item is not None and item.text().strip()) or widget is not None

        if not _is_filled(r0, c0):
            return

        # 四向扩展找边界
        r_top, r_bot = r0, r0
        while r_top > 0 and _is_filled(r_top - 1, c0):
            r_top -= 1
        while r_bot < rc - 1 and _is_filled(r_bot + 1, c0):
            r_bot += 1
        c_left, c_right = c0, c0
        while c_left > 0 and _is_filled(r0, c_left - 1):
            c_left -= 1
        while c_right < cc - 1 and _is_filled(r0, c_right + 1):
            c_right += 1

        top_left = self.table.model().index(r_top, c_left)
        bot_right = self.table.model().index(r_bot, c_right)
        self.table.selectionModel().select(
            QItemSelection(top_left, bot_right),
            self.table.selectionModel().ClearAndSelect)

    def _jump_to_data_edge(self, direction):
        """Ctrl+方向键：跳转到数据区域边缘"""
        cur = self.table.currentIndex()
        if not cur.isValid():
            return
        r, c = cur.row(), cur.column()
        dr = {'up': -1, 'down': 1, 'left': 0, 'right': 0}[direction]
        dc = {'up': 0, 'down': 0, 'left': -1, 'right': 1}[direction]
        rc, cc = self.table.rowCount(), self.table.columnCount()

        def _is_filled(rr, cc_co):
            item = self.table.item(rr, cc_co)
            widget = self.table.cellWidget(rr, cc_co)
            return (item is not None and item.text().strip()) or widget is not None

        nr, nc = r + dr, c + dc
        while 0 <= nr < rc and 0 <= nc < cc and _is_filled(nr, nc):
            nr += dr
            nc += dc
        nr -= dr
        nc -= dc
        if 0 <= nr < rc and 0 <= nc < cc:
            self.table.setCurrentCell(nr, nc)

    def _show_goto_dialog(self):
        """F5：定位对话框，输入行列号精准跳转"""
        from PyQt5.QtWidgets import QFormLayout, QSpinBox, QDialogButtonBox
        dlg = QDialog(self)
        dlg.setWindowTitle("转到单元格")
        dlg.setMinimumWidth(300)
        layout = QFormLayout(dlg)

        row_spin = QSpinBox()
        row_spin.setRange(1, self.table.rowCount())
        row_spin.setValue(self.table.currentRow() + 1)
        layout.addRow("行号:", row_spin)

        col_spin = QSpinBox()
        col_spin.setRange(1, self.table.columnCount())
        col_spin.setValue(self.table.currentColumn() + 1)
        layout.addRow("列号:", col_spin)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addRow(btns)

        if dlg.exec_() == QDialog.Accepted:
            r = row_spin.value() - 1
            c = col_spin.value() - 1
            if 0 <= r < self.table.rowCount() and 0 <= c < self.table.columnCount():
                self.table.setCurrentCell(r, c)

    # ── 行号/角标点击 ──────────────────────────────────────────────

    def _on_row_header_clicked(self, row):
        """点击行号 → 选中整行（#4）；Ctrl=追加行（#8）；Shift=连续行（#9）"""
        modifiers = QApplication.keyboardModifiers()
        sel = self.table.selectionModel()
        if modifiers & Qt.ControlModifier:
            # 切换该行的选中状态
            first_idx = self.table.model().index(row, 0)
            toggle_on = not sel.isSelected(first_idx)
            for c in range(self._col_count):
                idx = self.table.model().index(row, c)
                sel.select(idx, sel.Select if toggle_on else sel.Deselect)
        elif modifiers & Qt.ShiftModifier:
            self.table.selectRow(row)  # Qt ExtendedSelection 处理连续范围
        else:
            self.table.clearSelection()
            self.table.selectRow(row)

    def _on_corner_clicked(self):
        """点击左上角交叉处 → 全选所有单元格（#14）"""
        self.table.selectAll()

    def _do_auto_scroll(self):
        """自定义速度自动滚动（每次滚动 1 行）"""
        bar = self.table.verticalScrollBar()
        bar.setValue(bar.value() + self._auto_scroll_dir * bar.singleStep())

    def on_shown(self):
        self._refresh_filters()
        self._do_search()
        QTimer.singleShot(100, self._adjust_columns_delayed)

    def update_dynamic_styles(self):
        """字体缩放后重新渲染表格"""
        self._refresh_table()

    def _adjust_columns_delayed(self):
        self._restore_columns()
        self._apply_layout()
        self._rescale_images()
        self.table.resizeRowsToContents()

    def _rescale_images(self):
        """用当前列宽重新缩放完整图模式的图片"""
        if AppSettings().image_display_mode != "full":
            return
        for label, path, col in self._img_labels:
            if not os.path.exists(path):
                continue
            col_w = self.table.columnWidth(col) - 12
            if col_w < 50:
                continue
            pixmap = QPixmap(path)
            if pixmap.width() > col_w:
                pixmap = pixmap.scaledToWidth(col_w, Qt.SmoothTransformation)
            label.setPixmap(pixmap)

    def _restore_columns(self):
        """恢复持久化的可动列比例"""
        saved = AppSettings().load_table_columns("question_list")
        if saved and len(saved) == self._col_count:
            # saved[col] = ratio * 10000 (整数存储)
            ratios = {}
            total = 0
            for c in self._movable_cols:
                if c < len(saved) and saved[c] > 0:
                    ratios[c] = saved[c]
                    total += saved[c]
            if total > 0:
                self._movable_ratios = {c: v / total for c, v in ratios.items()}

    def _save_columns(self):
        """持久化可动列比例（×10000 整数存储），固定列存 0"""
        widths = [0] * self._col_count
        scale = 10000
        for c, r in self._movable_ratios.items():
            widths[c] = int(r * scale)
        AppSettings().save_table_columns("question_list", widths)

    def _refresh_filters(self):
        """重新加载分类和标签下拉框（含星标/错题特殊分类）"""
        # 使用 refreshing 标记防止 _do_search 在重建期间被触发
        self._refreshing = True

        self.cat_filter.blockSignals(True)
        self.tag_filter.blockSignals(True)

        try:
            self.cat_filter.clear()
            self.cat_filter.addItem("全部分类", userData=None)
            self.cat_filter.addItem("★ 星标收藏夹", userData=-1)
            self.cat_filter.addItem("✗ 错题集", userData=-2)
            # 分隔线：用 setItemEnabled(False) 禁掉
            self.cat_filter.addItem("──────────")
            self.cat_filter.setItemEnabled(3, False)
            for cat in models.get_all_categories():
                self.cat_filter.addItem(cat["name"], userData=cat["id"])
        finally:
            pass

        self.tag_filter.clear()
        self.tag_filter.addItem("全部标签", userData=None)
        for tag in models.get_all_tags():
            self.tag_filter.addItem(tag["name"], userData=tag["id"])

        # 先恢复 cat_filter 确保 currentIndex 正确再解除 blocking
        if self.cat_filter.count() > 0:
            self.cat_filter.setCurrentIndex(0)

        self.cat_filter.blockSignals(False)
        self.tag_filter.blockSignals(False)

        self._refreshing = False

        # 显示/隐藏分类操作按钮
        self._update_cat_btns()

        # 标签右键菜单 — 设在 ComboBox 自身上（qfluentwidgets 版无 view()）
        self.tag_filter.setContextMenuPolicy(Qt.CustomContextMenu)
        try:
            self.tag_filter.customContextMenuRequested.disconnect()
        except Exception:
            pass
        self.tag_filter.customContextMenuRequested.connect(
            self._on_tag_context_menu)

    def _edit_tag_dialog(self, tag_id):
        """点击标签徽章 → 编辑标签"""
        all_tags = models.get_all_tags()
        tag_info = next((t for t in all_tags if t["id"] == tag_id), None)
        if tag_info is None:
            return
        self._show_tag_editor(tag_id, tag_info["name"], tag_info.get("color", "#4A90D9"))

    def _show_tag_editor(self, tag_id, tag_name, tag_color):
        """标签编辑对话框（名称+颜色）"""
        dlg = QDialog(self)
        dlg.setWindowTitle("编辑标签")
        dlg.setMinimumSize(320, 150)
        dl = QVBoxLayout(dlg)
        nr = QHBoxLayout()
        nr.addWidget(QLabel("名称:"))
        ne = LineEdit(tag_name)
        nr.addWidget(ne)
        dl.addLayout(nr)
        cr = QHBoxLayout()
        cr.addWidget(QLabel("颜色:"))
        cb = PushButton()
        cb.setFixedSize(28, 28)
        cur = [tag_color]
        cb.setStyleSheet(f"background-color: {cur[0]}; border:1px solid #999; border-radius:4px;")
        def epc():
            c = QColorDialog.getColor()
            if c.isValid():
                cur[0] = c.name()
                cb.setStyleSheet(f"background-color:{c.name()}; border:1px solid #999; border-radius:4px;")
        cb.clicked.connect(epc)
        cr.addWidget(cb)
        dl.addLayout(cr)
        presets = ['#E74C3C','#E67E22','#F1C40F','#2ECC71','#1ABC9C',
                   '#3498DB','#9B59B6','#E91E63','#795548','#95A5A6']
        pr = QHBoxLayout()
        pr.setSpacing(4)
        for pc in presets:
            pb = PushButton()
            pb.setFixedSize(20, 20)
            pb.setStyleSheet(f"background-color:{pc}; border:1px solid #999; border-radius:10px;")
            pb.clicked.connect(lambda checked, c=pc, b=cb, nc=cur:
                nc.__setitem__(0, c) or b.setStyleSheet(
                    f"background-color:{c}; border:1px solid #999; border-radius:4px;"))
            pr.addWidget(pb)
        dl.addLayout(pr)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        dl.addWidget(bb)
        if dlg.exec_() == QDialog.Accepted and ne.text().strip():
            from database import db_manager
            conn = db_manager.get_connection()
            conn.execute("UPDATE tags SET name=?, color=? WHERE id=?",
                         (ne.text().strip(), cur[0], tag_id))
            conn.commit()
            conn.close()
            self._refresh_filters()
            self._do_search()

    def _on_tag_context_menu(self, pos):
        """标签右键菜单：编辑 / 删除"""
        tag_id = self.tag_filter.currentData()
        tag_name = self.tag_filter.currentText()
        if tag_id is None:
            return
        all_tags = models.get_all_tags()
        tag_info = next((t for t in all_tags if t["id"] == tag_id), None)
        if tag_info is None:
            return

        menu = QMenu(self)
        edit_action = menu.addAction("编辑标签")
        del_action = menu.addAction("删除标签")
        action = menu.exec_(self.tag_filter.mapToGlobal(pos))

        if action == edit_action:
            self._show_tag_editor(tag_id, tag_name, tag_info.get("color", "#4A90D9"))

        elif action == del_action:
            reply = QMessageBox.question(
                self, "确认删除",
                f"确定要删除标签「{tag_name}」吗？\n（题目不会删除，仅移除标签关联）",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.Yes:
                models.delete_tag(tag_id)
                self._refresh_filters()
                self._do_search()

    def _update_cat_btns(self):
        """当前分类为普通分类时显示重命名/删除按钮"""
        cat_id = self.cat_filter.currentData()
        show = cat_id not in (None, -1, -2)
        self.cat_rename_btn.setVisible(show)
        self.cat_del_btn.setVisible(show)

    def _rename_category(self):
        """重命名当前选中的分类"""
        cat_id = self.cat_filter.currentData()
        cat_name = self.cat_filter.currentText()
        if cat_id in (None, -1, -2):
            return
        new_name, ok = QInputDialog.getText(
            self, "重命名分类", "新名称：", text=cat_name)
        if ok and new_name.strip() and new_name.strip() != cat_name:
            models.rename_category(cat_id, new_name.strip())
            self._refresh_filters()
            self._do_search()

    def _delete_category(self):
        """删除当前选中的分类"""
        cat_id = self.cat_filter.currentData()
        cat_name = self.cat_filter.currentText()
        if cat_id in (None, -1, -2):
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f'确定要删除分类「{cat_name}」吗？\n（题目不会被删除，分类将变为"无分类"）',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            models.delete_category(cat_id)
            self._refresh_filters()
            self._do_search()

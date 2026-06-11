"""
题库管理面板 - QTableView + QAbstractTableModel + QStyledItemDelegate 重构版

MVP 架构分离：
- QuestionTableModel    → 纯数据层 (all_questions → Qt roles)
- QuestionDelegate      → 渲染+交互层 (paint + editorEvent 统一处理点击)
- QuestionListPanel     → 视图层 (QTableView + 搜索/筛选/分页/快捷键/批量操作)
"""
import os
import subprocess
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableView, QHeaderView, QAbstractItemView, QFrame,
    QMessageBox, QMenu, QStyle,
    QFileDialog, QProgressDialog, QApplication, QInputDialog,
    QDialog, QCheckBox, QDialogButtonBox, QColorDialog,
    QStyledItemDelegate, QStyleOptionButton,
)
from PyQt5.QtCore import (
    Qt, pyqtSignal, QTimer, QEvent, QItemSelection,
    QAbstractTableModel, QModelIndex, QRect, QSize,
)
from PyQt5.QtGui import (
    QPixmap, QIcon, QFontMetrics, QKeySequence, QColor,
    QPainter, QPen, QFont, QPalette,
)
from qfluentwidgets import (
    PrimaryPushButton, PushButton, ComboBox, LineEdit, CardWidget,
)
from database import models
from config import AppSettings
from services.export_service import export_questions

PAGE_SIZE = 20
THUMB_SIZE = 50

# 列索引常量（方便引用）
COL_SEL, COL_IDX, COL_UID, COL_STAR, COL_QUESTION, COL_CAT = range(6)
COL_TAGS, COL_ANSWER, COL_NOTES, COL_WRONG, COL_DATE, COL_OPS = range(6, 12)
COL_COUNT = 12

HEADERS = ["选中状态", "序号", "初始编号", "星标", "题目", "分类",
           "标签", "答案", "备注", "错次", "最近修改", "操作"]
# 可排序列（索引 → key 函数）
SORT_KEYS = {
    COL_UID:      lambda q: q.get("uid", ""),
    COL_STAR:     lambda q: q.get("starred", 0),
    COL_QUESTION: lambda q: q.get("question_text", ""),
    COL_CAT:      lambda q: q.get("category_id") or 0,
    COL_TAGS:     lambda q: q.get("_tags_str", ""),
    COL_ANSWER:   lambda q: q.get("answer_text", ""),
    COL_NOTES:    lambda q: q.get("notes", ""),
    COL_WRONG:    lambda q: q.get("wrong_count", 0),
    COL_DATE:     lambda q: q.get("updated_at", ""),
}


# ============================================================================
# Model — 纯数据层
# ============================================================================
class QuestionTableModel(QAbstractTableModel):
    """将 self.all_questions 暴露为 Qt 表格模型"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._questions = []       # 当前页的题目列表
        self._base_index = 0       # 起始全局索引
        self._total_count = 0      # 全部题目数
        self._selection = set()    # 被选中的题目 ID 集合
        self._image_mode = "thumb"
        self._images_cache = {}    # qid → (q_images, a_images)

    # ── 必须实现 ──
    def rowCount(self, parent=QModelIndex()):
        return len(self._questions)

    def columnCount(self, parent=QModelIndex()):
        return COL_COUNT

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        if r >= len(self._questions):
            return None
        q = self._questions[r]

        if role == Qt.DisplayRole:
            return self._display_data(q, c, r)
        if role == Qt.TextAlignmentRole:
            return self._alignment(c)
        if role == Qt.CheckStateRole and c == COL_SEL:
            return Qt.Checked if q["id"] in self._selection else Qt.Unchecked
        if role == Qt.ForegroundRole and c == COL_WRONG:
            if q.get("wrong_count", 0) > 0:
                return QColor(255, 0, 0)
        if role == Qt.UserRole:
            return q
        if role == Qt.UserRole + 1:
            return self._images_cache.get(q["id"], ([], []))
        return None

    def _display_data(self, q, col, row):
        if col == COL_IDX:
            return str(self._base_index + row + 1)
        if col == COL_UID:
            return q.get("uid", "") or "-"
        if col == COL_QUESTION:
            return q.get("question_text", "")
        if col == COL_CAT:
            return self._cat_name(q.get("category_id"))
        if col == COL_ANSWER:
            return q.get("answer_text", "")
        if col == COL_NOTES:
            return q.get("notes", "")
        if col == COL_WRONG:
            return str(q.get("wrong_count", 0))
        if col == COL_DATE:
            u = q.get("updated_at", "")
            if u and len(u) > 16:
                return u[:10].replace("-", "/") + " " + u[11:19]
            return u or "-"
        return ""

    def _alignment(self, col):
        if col in (COL_SEL, COL_IDX, COL_UID, COL_WRONG, COL_DATE):
            return Qt.AlignCenter
        return Qt.AlignLeft | Qt.AlignVCenter

    def _cat_name(self, cat_id):
        if not cat_id:
            return ""
        if not hasattr(self, '_cat_map'):
            self._cat_map = {}
            for c in models.get_all_categories():
                self._cat_map[c["id"]] = c["name"]
        return self._cat_map.get(cat_id, "")

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if 0 <= section < len(HEADERS):
                return HEADERS[section]
        return None

    def flags(self, index):
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == COL_SEL:
            f |= Qt.ItemIsUserCheckable
        return f

    def setData(self, index, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and index.column() == COL_SEL:
            q = self._questions[index.row()]
            if value == Qt.Checked:
                self._selection.add(q["id"])
            else:
                self._selection.discard(q["id"])
            self.dataChanged.emit(index, index, [Qt.CheckStateRole])
            return True
        return False

    # ── 公开 API ──
    def selected_ids(self):
        return self._selection.copy()

    def load_page(self, all_questions, page, total, image_mode):
        """加载一页数据，返回被选中 ID 集合"""
        self.beginResetModel()
        self._image_mode = image_mode
        self._total_count = total
        self._base_index = page * PAGE_SIZE
        start = self._base_index
        end = min(start + PAGE_SIZE, len(all_questions))
        self._questions = all_questions[start:end]
        # 预加载图片信息
        self._images_cache.clear()
        for q in self._questions:
            imgs = models.get_question_images(q["id"])
            q_imgs = [i for i in imgs if i["image_type"] == "question"]
            a_imgs = [i for i in imgs if i["image_type"] == "answer"]
            self._images_cache[q["id"]] = (q_imgs, a_imgs)
        # 定期刷新分类名映射
        if not hasattr(self, '_cat_map'):
            self._cat_map = {}
            for c in models.get_all_categories():
                self._cat_map[c["id"]] = c["name"]
        self.endResetModel()
        return self._selection.copy()

    def question_at_row(self, row):
        if 0 <= row < len(self._questions):
            return self._questions[row]
        return None

    def get_question_row(self, qid):
        for r, q in enumerate(self._questions):
            if q["id"] == qid:
                return r
        return -1

    def toggle_star(self, qid):
        """切换星标，返回新状态"""
        new_val = models.toggle_star(qid)
        for i, q in enumerate(self._questions):
            if q["id"] == qid:
                q["starred"] = new_val
                idx = self.index(i, COL_STAR)
                self.dataChanged.emit(idx, idx)
                break
        return new_val

    def updated(self):
        """通知视图全部数据已刷新"""
        self._cat_map = {}
        for c in models.get_all_categories():
            self._cat_map[c["id"]] = c["name"]
        if self._questions:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self._questions) - 1, COL_COUNT - 1))


# ============================================================================
# Delegate — 渲染 + 交互层（统一所有单元格事件，消除 widget vs item 差异）
# ============================================================================
class QuestionDelegate(QStyledItemDelegate):
    """绘制星标、标签芯片、答案区、操作按钮，并通过 editorEvent 处理点击"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._panel = None  # 回引 QuestionListPanel

    def paint(self, painter, option, index):
        col = index.column()
        if col == COL_STAR:
            self._paint_star(painter, option, index)
        elif col == COL_TAGS:
            self._paint_tags(painter, option, index)
        elif col == COL_ANSWER:
            self._paint_answer(painter, option, index)
        elif col == COL_OPS:
            self._paint_ops(painter, option, index)
        elif col == COL_QUESTION:
            self._paint_question(painter, option, index)
        else:
            super().paint(painter, option, index)

    def sizeHint(self, option, index):
        col = index.column()
        if col == COL_STAR:
            return QSize(40, 44)
        if col == COL_OPS:
            return QSize(180, 44)
        return super().sizeHint(option, index)

    def editorEvent(self, event, model, option, index):
        """统一事件入口：所有鼠标点击都在这里处理"""
        if event.type() == QEvent.MouseButtonRelease:
            col = index.column()
            if col == COL_STAR:
                return self._on_star_click(index, model)
            elif col == COL_ANSWER:
                return self._on_answer_click(index, model)
            elif col == COL_TAGS:
                return self._on_tags_click(event, option, index, model)
            elif col == COL_OPS:
                return self._on_ops_click(event, option, index, model)
        return super().editorEvent(event, model, option, index)

    # ── 绘制 ──
    def _paint_star(self, painter, option, index):
        q = index.data(Qt.UserRole)
        if not q:
            return
        is_starred = bool(q.get("starred", 0))
        painter.save()
        rect = option.rect
        cx, cy = rect.center().x(), rect.center().y()
        r = 18
        if is_starred:
            painter.setPen(QPen(QColor("#F5A623"), 1))
            painter.setBrush(QColor("#FFF8E1"))
        else:
            painter.setPen(QPen(QColor("#DDD"), 1))
            painter.setBrush(QColor("#FAFAFA"))
        painter.drawEllipse(int(cx - r), int(cy - r), 2 * r, 2 * r)
        painter.setPen(QColor("#F5A623") if is_starred else QColor("#BBB"))
        f = QFont()
        f.setPointSize(16)
        painter.setFont(f)
        painter.drawText(QRect(int(cx - r), int(cy - r), 2 * r, 2 * r),
                         Qt.AlignCenter, "★" if is_starred else "☆")
        painter.restore()

    def _paint_tags(self, painter, option, index):
        q = index.data(Qt.UserRole)
        if not q:
            return
        tags = models.get_question_tags(q["id"])
        painter.save()
        x, y = option.rect.x() + 4, option.rect.y() + 4
        for t in tags:
            text = t["name"]
            color = QColor(t.get("color", "#4A90D9"))
            fm = QFontMetrics(option.font)
            tw = fm.width(text) + 20
            chip_rect = QRect(x, y, tw, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(chip_rect, 10, 10)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(option.font)
            painter.drawText(chip_rect, Qt.AlignCenter, text)
            x += tw + 4
            if x > option.rect.right():
                break
        painter.restore()

    def _paint_answer(self, painter, option, index):
        q = index.data(Qt.UserRole)
        if not q:
            return
        panel = self._panel
        show = panel and index.row() in getattr(panel, '_expanded_answers', set())
        if show:
            q_imgs, a_imgs = index.data(Qt.UserRole + 1)
            a_text = q.get("answer_text", "")
            painter.save()
            rect = option.rect
            y = rect.y() + 4
            if a_imgs and os.path.exists(a_imgs[0]["image_path"]):
                pixmap = QPixmap(a_imgs[0]["image_path"])
                if pixmap.width() > rect.width() - 8:
                    pixmap = pixmap.scaledToWidth(rect.width() - 8, Qt.SmoothTransformation)
                painter.drawPixmap(rect.x() + 4, y, pixmap)
                y += pixmap.height() + 4
            if a_text:
                painter.setPen(Qt.black)
                painter.setFont(option.font)
                text_rect = QRect(rect.x() + 4, y, rect.width() - 8, rect.height() - (y - rect.y()))
                painter.drawText(text_rect, Qt.AlignLeft | Qt.TextWordWrap, a_text)
            painter.restore()
        else:
            painter.save()
            painter.setPen(QColor("#666"))
            btn_rect = option.rect.adjusted(10, 8, -10, -8)
            painter.setBrush(QColor("#D0D0D0"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(btn_rect, 4, 4)
            painter.setPen(QColor("#666"))
            painter.drawText(btn_rect, Qt.AlignCenter, "点击查看答案")
            painter.restore()

    def _paint_ops(self, painter, option, index):
        painter.save()
        rect = option.rect
        # 编辑按钮
        edit_rect = QRect(rect.x() + 4, rect.y() + 6, 50, 30)
        painter.setBrush(QColor("#E8E8E8"))
        painter.setPen(QPen(QColor("#CCC"), 1))
        painter.drawRoundedRect(edit_rect, 4, 4)
        painter.setPen(QColor("#333"))
        painter.drawText(edit_rect, Qt.AlignCenter, "编辑")
        # 删除按钮
        del_rect = QRect(rect.x() + 60, rect.y() + 6, 50, 30)
        painter.setBrush(QColor("#FFE8E8"))
        painter.setPen(QPen(QColor("#FFB0B0"), 1))
        painter.drawRoundedRect(del_rect, 4, 4)
        painter.setPen(QColor("#C00"))
        painter.drawText(del_rect, Qt.AlignCenter, "删除")
        painter.restore()

    def _paint_question(self, painter, option, index):
        q = index.data(Qt.UserRole)
        if not q:
            super().paint(painter, option, index)
            return
        q_imgs, a_imgs = index.data(Qt.UserRole + 1)
        mode = AppSettings().image_display_mode
        painter.save()
        rect = option.rect
        y = rect.y() + 4
        if q_imgs and os.path.exists(q_imgs[0]["image_path"]):
            pixmap = QPixmap(q_imgs[0]["image_path"])
            if mode == "full":
                if pixmap.width() > rect.width() - 8:
                    pixmap = pixmap.scaledToWidth(rect.width() - 8, Qt.SmoothTransformation)
            else:
                pixmap = pixmap.scaled(THUMB_SIZE, THUMB_SIZE,
                                       Qt.KeepAspectRatio, Qt.SmoothTransformation)
            painter.drawPixmap(rect.x() + 4, y, pixmap)
            y += pixmap.height() + 4
        text = q.get("question_text", "")
        if text:
            painter.setPen(Qt.black)
            painter.setFont(option.font)
            text_rect = QRect(rect.x() + 4, y, rect.width() - 8, rect.height() - (y - rect.y()))
            painter.drawText(text_rect, Qt.AlignLeft | Qt.TextWordWrap, text)
        painter.restore()

    # ── 交互 ──
    def _on_star_click(self, index, model):
        q = index.data(Qt.UserRole)
        if q and self._panel:
            self._panel._on_star_toggled(q["id"])
            return True
        return False

    def _on_answer_click(self, index, model):
        if self._panel:
            row = index.row()
            expanded = getattr(self._panel, '_expanded_answers', set())
            if row in expanded:
                expanded.discard(row)
            else:
                expanded.add(row)
            self._panel._expanded_answers = expanded
            # 触发整行重绘
            model.dataChanged.emit(
                model.index(row, 0), model.index(row, COL_COUNT - 1))
            self._panel._update_row_height(row)
            return True
        return False

    def _on_tags_click(self, event, option, index, model):
        q = index.data(Qt.UserRole)
        if not q or not self._panel:
            return False
        tags = models.get_question_tags(q["id"])
        pos = event.pos()
        x = 4
        opt_rect = option.rect
        for t in tags:
            text = t["name"]
            tw = QFontMetrics(QFont()).width(text) + 20
            chip_rect = QRect(opt_rect.x() + x, opt_rect.y() + 4, tw, 22)
            if chip_rect.contains(pos):
                self._panel._safe_edit_tag(t["id"])
                return True
            x += tw + 4
        return False

    def _on_ops_click(self, event, option, index, model):
        q = index.data(Qt.UserRole)
        if not q or not self._panel:
            return False
        pos = event.pos()
        rect = option.rect
        edit_rect = QRect(rect.x() + 4, rect.y() + 6, 50, 30)
        del_rect = QRect(rect.x() + 60, rect.y() + 6, 50, 30)
        if edit_rect.contains(pos):
            self._panel.edit_requested.emit(q["id"])
            return True
        if del_rect.contains(pos):
            self._panel._delete_question(q["id"])
            return True
        return False


# ============================================================================
# HighlightHeader — 支持选中高亮的表头
# ============================================================================
class HighlightHeader(QHeaderView):
    """选中单元格所在行/列的表头半透明蓝色高亮"""
    _table_ref = None

    def paintSection(self, painter, rect, logicalIndex):
        super().paintSection(painter, rect, logicalIndex)
        if self._table_ref is None:
            return
        sel = self._table_ref.selectionModel()
        if sel is None:
            return
        highlighted = False
        if self.orientation() == Qt.Vertical:
            model = self._table_ref.model()
            for c in range(model.columnCount()):
                if sel.isSelected(model.index(logicalIndex, c)):
                    highlighted = True
                    break
        else:
            model = self._table_ref.model()
            for r in range(model.rowCount()):
                if sel.isSelected(model.index(r, logicalIndex)):
                    highlighted = True
                    break
        if highlighted:
            painter.save()
            painter.setOpacity(0.35)
            painter.fillRect(rect, QColor("#4A90D9"))
            painter.restore()


# ============================================================================
# QuestionListPanel — 主面板
# ============================================================================
class QuestionListPanel(QWidget):
    """题库管理面板：QTableView + MVC + 搜索筛选 + 分页 + 快捷键"""

    edit_requested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.all_questions = []
        self.current_page = 0
        self._sort_col = -1
        self._sort_state = 0
        self._original_order = []
        self._expanded_answers = set()
        self._dragging = False
        self._auto_scroll_dir = 0
        self._shortcut_actions = {}
        self._setup_ui()
        self._setup_shortcuts()

    # ── UI 构建 ──
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)

        title = QLabel("题库管理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # 搜索/筛选栏
        filter_frame = CardWidget()
        filter_frame.setObjectName("card")
        fl = QHBoxLayout(filter_frame)
        fl.setContentsMargins(16, 10, 16, 10)
        fl.setSpacing(12)

        fl.addWidget(QLabel("搜索："))
        self.search_input = LineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索...")
        self.search_input.setMaximumWidth(220)
        self.search_input.textChanged.connect(self._do_search)
        fl.addWidget(self.search_input)

        fl.addWidget(QLabel("分类："))
        self.cat_filter = ComboBox()
        self.cat_filter.currentIndexChanged.connect(self._do_search)
        self.cat_filter.currentIndexChanged.connect(self._update_cat_btns)
        fl.addWidget(self.cat_filter)

        self.cat_rename_btn = PushButton("重命名")
        self.cat_rename_btn.setObjectName("smallBtn")
        self.cat_rename_btn.setCursor(Qt.PointingHandCursor)
        self.cat_rename_btn.setVisible(False)
        self.cat_rename_btn.clicked.connect(self._rename_category)
        fl.addWidget(self.cat_rename_btn)

        self.cat_del_btn = PushButton("删除")
        self.cat_del_btn.setObjectName("dangerBtn")
        self.cat_del_btn.setCursor(Qt.PointingHandCursor)
        self.cat_del_btn.setVisible(False)
        self.cat_del_btn.clicked.connect(self._delete_category)
        fl.addWidget(self.cat_del_btn)

        fl.addWidget(QLabel("标签："))
        self.tag_filter = ComboBox()
        self.tag_filter.currentIndexChanged.connect(self._do_search)
        fl.addWidget(self.tag_filter)

        fl.addStretch()

        self.sort_btn = PushButton("排序 ▾")
        self.sort_btn.setObjectName("secondaryBtn")
        self.sort_btn.setCursor(Qt.PointingHandCursor)
        self.sort_btn.clicked.connect(
            lambda: self._show_sort_menu(
                self.sort_btn.mapToGlobal(self.sort_btn.rect().bottomLeft())))
        fl.addWidget(self.sort_btn)

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
        fl.addWidget(self.batch_btn)

        layout.addWidget(filter_frame)

        # 统计栏
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

        # ── QTableView ──
        self.table = QTableView()
        self.model = QuestionTableModel(self.table)
        self.delegate = QuestionDelegate(self.table)
        self.delegate._panel = self
        self.table.setModel(self.model)
        self.table.setItemDelegate(self.delegate)

        # 表头
        self.table.setVerticalHeader(HighlightHeader(Qt.Vertical))
        self.table.setHorizontalHeader(HighlightHeader(Qt.Horizontal))
        self.table.verticalHeader()._table_ref = self.table
        self.table.horizontalHeader()._table_ref = self.table
        vh = self.table.verticalHeader()
        vh.setSectionsClickable(True)
        vh.sectionClicked.connect(self._on_row_header_clicked)
        hh = self.table.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.sectionClicked.connect(self._on_header_clicked)
        hh.setContextMenuPolicy(Qt.CustomContextMenu)
        hh.customContextMenuRequested.connect(self._on_header_context_menu)
        # 角标按钮
        from PyQt5.QtWidgets import QAbstractButton
        corner = self.table.findChild(QAbstractButton)
        if corner:
            corner.clicked.connect(self._on_corner_clicked)

        # 选择行为
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setAutoScroll(False)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setShowGrid(True)

        # 选中变化
        self.table.selectionModel().selectionChanged.connect(
            self._on_selection_changed)

        # 列宽
        self._setup_columns()

        # 事件过滤
        self.table.viewport().installEventFilter(self)
        self.table.installEventFilter(self)

        # 自动滚动
        self._auto_scroll_timer = QTimer()
        self._auto_scroll_timer.timeout.connect(self._do_auto_scroll)

        layout.addWidget(self.table)

        # 列筛选菜单
        self._col_menu = QMenu(self)
        for c in range(COL_COUNT):
            if c in (COL_SEL, COL_IDX, COL_OPS):
                continue
            action = self._col_menu.addAction(HEADERS[c])
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(c))
            action.setData(c)
            action.toggled.connect(
                lambda checked, col=c: self.table.setColumnHidden(col, not checked))
        self.col_filter_btn.clicked.connect(
            lambda: self._col_menu.exec_(
                self.col_filter_btn.mapToGlobal(self.col_filter_btn.rect().bottomLeft())))

        # 翻页
        page_frame = CardWidget()
        page_frame.setObjectName("card")
        pl = QHBoxLayout(page_frame)
        pl.setContentsMargins(12, 8, 12, 8)
        pl.setSpacing(10)

        self.prev_btn = PushButton("◀ 上一页")
        self.prev_btn.setObjectName("smallBtn")
        self.prev_btn.clicked.connect(self._prev_page)
        pl.addWidget(self.prev_btn)
        pl.addStretch()
        self.page_label = QLabel()
        self.page_label.setObjectName("statusLabel")
        pl.addWidget(self.page_label)
        pl.addStretch()
        self.next_btn = PushButton("下一页 ▶")
        self.next_btn.setObjectName("smallBtn")
        self.next_btn.clicked.connect(self._next_page)
        pl.addWidget(self.next_btn)
        layout.addWidget(page_frame)

        # 初始隐藏列
        self.table.setColumnHidden(COL_UID, True)
        self.table.setColumnHidden(COL_NOTES, True)

    def _setup_columns(self):
        hh = self.table.horizontalHeader()
        fm = QFontMetrics(hh.font())
        # 固定列
        for c, w in [(COL_SEL, 60), (COL_IDX, 80), (COL_OPS, 180)]:
            self.table.setColumnWidth(c, w)
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
        # 可拉伸列
        stretch_cols = [COL_UID, COL_STAR, COL_QUESTION, COL_CAT,
                        COL_TAGS, COL_ANSWER, COL_NOTES, COL_WRONG, COL_DATE]
        for c in stretch_cols:
            hh.setSectionResizeMode(c, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_UID, 140)
        self.table.setColumnWidth(COL_STAR, 50)
        self.table.setColumnWidth(COL_QUESTION, 500)
        self.table.setColumnWidth(COL_CAT, 100)
        self.table.setColumnWidth(COL_TAGS, 150)
        self.table.setColumnWidth(COL_ANSWER, 200)
        self.table.setColumnWidth(COL_NOTES, 120)
        self.table.setColumnWidth(COL_WRONG, 60)
        self.table.setColumnWidth(COL_DATE, 140)
        # 题目列自动拉伸
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(COL_QUESTION, QHeaderView.Stretch)

    def _setup_shortcuts(self):
        self._shortcut_actions = {
            "select_all":  lambda: self.table.selectAll(),
            "goto_dialog": self._show_goto_dialog,
            "select_col":  self._handle_select_col,
            "select_row":  self._handle_select_row,
            "select_region": self._select_current_region,
            "jump_edge_up":    lambda: self._jump_to_data_edge('up'),
            "jump_edge_down":  lambda: self._jump_to_data_edge('down'),
            "jump_edge_left":  lambda: self._jump_to_data_edge('left'),
            "jump_edge_right": lambda: self._jump_to_data_edge('right'),
            "prev_page": self._prev_page,
            "next_page": self._next_page,
            "clear_selection": lambda: self.table.clearSelection(),
        }

    # ── 属性 ──
    @property
    def _selected_ids(self):
        return self.model.selected_ids()

    # ── 搜索与数据 ──
    def _total_pages(self):
        return max(1, (len(self.all_questions) + PAGE_SIZE - 1) // PAGE_SIZE)

    def _do_search(self):
        if getattr(self, '_refreshing', False):
            return
        try:
            keyword = self.search_input.text().strip()
            cat_id = self.cat_filter.currentData()
            tag_id = self.tag_filter.currentData()
        except Exception:
            return
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
        for q in self.all_questions:
            tags = models.get_question_tags(q["id"])
            q["_tags_str"] = ", ".join(t["name"] for t in tags)
        self._original_order = self.all_questions[:]
        if self._sort_col >= 0 and self._sort_state > 0:
            self._apply_sort()
        else:
            self.current_page = 0
            self._refresh_table()

    def _refresh_table(self):
        total = len(self.all_questions)
        total_pages = self._total_pages()
        if self.current_page >= total_pages:
            self.current_page = total_pages - 1
        saved = self._selected_ids.copy()
        self.model._selection = saved
        self._expanded_answers.clear()
        self.model.load_page(self.all_questions, self.current_page,
                             total, AppSettings().image_display_mode)
        # 恢复选中
        if saved:
            for r, q in enumerate(self.model._questions):
                if q["id"] in saved:
                    self.table.selectRow(r)
        # 更新UI
        self._update_pagination(total, total_pages)
        self._on_selection_changed()

    def _update_pagination(self, total, total_pages):
        self.stats_label.setText(f"共 {total} 道题目")
        self.page_label.setText(
            f"第 {self.current_page + 1} / {total_pages} 页")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < total_pages - 1)

    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._refresh_table()

    def _next_page(self):
        if self.current_page < self._total_pages() - 1:
            self.current_page += 1
            self._refresh_table()

    def _get_question_at_row(self, row):
        return self.model.question_at_row(row)

    # ── 选择同步 ──
    def _on_selection_changed(self):
        # 从 Qt 选择模型同步到 model._selection
        sel_model = self.table.selectionModel()
        model = self.model
        new_ids = set()
        rows_seen = set()
        for idx in sel_model.selectedIndexes():
            r = idx.row()
            if r not in rows_seen:
                rows_seen.add(r)
                q = model.question_at_row(r)
                if q:
                    new_ids.add(q["id"])
        model._selection = new_ids

        # 更新标签
        count = len(new_ids)
        total = len(self.all_questions)
        if count:
            self.stats_label.setText(f"共 {total} 道题目 | 已选中 {count} 道")
        else:
            self.stats_label.setText(f"共 {total} 道题目")

        # 刷新表头（高亮）
        self.table.verticalHeader().viewport().update()
        self.table.horizontalHeader().viewport().update()

        # 通知 model 刷新复选框列
        top = model.index(0, COL_SEL)
        bot = model.index(model.rowCount() - 1, COL_SEL)
        model.dataChanged.emit(top, bot, [Qt.CheckStateRole])

    def _on_star_toggled(self, qid):
        self.model.toggle_star(qid)

    # ── 排序 ──
    def _on_header_clicked(self, col):
        """列头点击 = 选中整列"""
        modifiers = QApplication.keyboardModifiers()
        sel = self.table.selectionModel()
        model = self.model
        if modifiers & Qt.ControlModifier:
            for r in range(model.rowCount()):
                sel.select(model.index(r, col), sel.Select)
        elif modifiers & Qt.ShiftModifier:
            self.table.selectColumn(col)
        else:
            self.table.clearSelection()
            self.table.selectColumn(col)

    def _on_header_context_menu(self, pos):
        col = self.table.horizontalHeader().logicalIndexAt(pos)
        if col not in SORT_KEYS:
            return
        menu = QMenu(self)
        menu.addAction("↑ 升序排列", lambda: self._set_sort(col, 1))
        menu.addAction("↓ 降序排列", lambda: self._set_sort(col, 2))
        menu.addAction("— 恢复默认顺序", lambda: self._set_sort(-1, 0))
        menu.exec_(self.table.horizontalHeader().viewport().mapToGlobal(pos))

    def _set_sort(self, col, state):
        if state == 0:
            self._sort_col = -1
            self._sort_state = 0
            self.sort_btn.setText("排序 ▾")
        else:
            self._sort_col = col
            self._sort_state = state
            arrow = " ↑" if state == 1 else " ↓"
            self.sort_btn.setText(f"排序: {HEADERS[col]}{arrow}")
        self._apply_sort()

    def _show_sort_menu(self, global_pos):
        menu = QMenu(self)
        menu.addAction("— 恢复默认顺序", lambda: self._set_sort(-1, 0))
        menu.addSeparator()
        for col, header in enumerate(HEADERS):
            if col in SORT_KEYS:
                menu.addAction(f"↑ {header} 升序", lambda c=col: self._set_sort(c, 1))
                menu.addAction(f"↓ {header} 降序", lambda c=col: self._set_sort(c, 2))
        menu.exec_(global_pos)

    def _apply_sort(self):
        hh = self.table.horizontalHeader()
        if self._sort_state == 0:
            if self._original_order:
                self.all_questions = self._original_order[:]
            hh.setSortIndicatorShown(False)
            self._sort_col = -1
        else:
            key = SORT_KEYS.get(self._sort_col)
            if key:
                self.all_questions.sort(key=key, reverse=(self._sort_state == 2))
            hh.setSortIndicator(
                self._sort_col,
                Qt.AscendingOrder if self._sort_state == 1 else Qt.DescendingOrder)
            hh.setSortIndicatorShown(True)
        self.current_page = 0
        self._refresh_table()

    # ── 行高 ──
    def _update_row_height(self, row):
        self.table.resizeRowToContents(row)

    # ── 键盘快捷键 ──
    def _parse_key_event(self, event):
        parts = []
        if event.modifiers() & Qt.ControlModifier:
            parts.append("Ctrl")
        if event.modifiers() & Qt.ShiftModifier:
            parts.append("Shift")
        if event.modifiers() & Qt.AltModifier:
            parts.append("Alt")
        key = event.key()
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            return None
        key_name = QKeySequence(key).toString()
        if key_name:
            parts.append(key_name)
        return "+".join(parts) if parts else key_name

    def keyPressEvent(self, event):
        key_seq = self._parse_key_event(event)
        if key_seq is None:
            super().keyPressEvent(event)
            return
        settings = AppSettings()
        for action_id, handler in self._shortcut_actions.items():
            if settings.get_shortcut(action_id) == key_seq:
                handler()
                return
        super().keyPressEvent(event)

    # ── 选择操作 ──
    def _handle_select_col(self):
        cur = self.table.currentIndex()
        if cur.isValid():
            self.table.selectColumn(cur.column())

    def _handle_select_row(self):
        cur = self.table.currentIndex()
        if cur.isValid():
            self.table.selectRow(cur.row())

    def _select_current_region(self):
        cur = self.table.currentIndex()
        if not cur.isValid():
            return
        r0, c0 = cur.row(), cur.column()
        rc, cc = self.model.rowCount(), self.model.columnCount()

        def filled(r, c):
            idx = self.model.index(r, c)
            return bool(idx.data(Qt.DisplayRole)) or bool(idx.data(Qt.UserRole))

        if not filled(r0, c0):
            return

        r_top = r_bot = r0
        while r_top > 0 and filled(r_top - 1, c0):
            r_top -= 1
        while r_bot < rc - 1 and filled(r_bot + 1, c0):
            r_bot += 1
        c_left = c_right = c0
        while c_left > 0 and filled(r0, c_left - 1):
            c_left -= 1
        while c_right < cc - 1 and filled(r0, c_right + 1):
            c_right += 1

        top_left = self.model.index(r_top, c_left)
        bot_right = self.model.index(r_bot, c_right)
        self.table.selectionModel().select(
            QItemSelection(top_left, bot_right),
            self.table.selectionModel().ClearAndSelect)

    def _jump_to_data_edge(self, direction):
        cur = self.table.currentIndex()
        if not cur.isValid():
            return
        r, c = cur.row(), cur.column()
        dr = {'up': -1, 'down': 1, 'left': 0, 'right': 0}[direction]
        dc = {'up': 0, 'down': 0, 'left': -1, 'right': 1}[direction]
        rc, cc = self.model.rowCount(), self.model.columnCount()

        def filled(rr, cc_co):
            idx = self.model.index(rr, cc_co)
            return bool(idx.data(Qt.DisplayRole)) or bool(idx.data(Qt.UserRole))

        nr, nc = r + dr, c + dc
        while 0 <= nr < rc and 0 <= nc < cc and filled(nr, nc):
            nr += dr
            nc += dc
        nr -= dr
        nc -= dc
        if 0 <= nr < rc and 0 <= nc < cc:
            self.table.setCurrentIndex(self.model.index(nr, nc))

    def _show_goto_dialog(self):
        from PyQt5.QtWidgets import QFormLayout, QSpinBox
        dlg = QDialog(self)
        dlg.setWindowTitle("转到单元格")
        dlg.setMinimumWidth(300)
        layout = QFormLayout(dlg)
        row_spin = QSpinBox()
        row_spin.setRange(1, self.model.rowCount())
        row_spin.setValue(self.table.currentIndex().row() + 1)
        layout.addRow("行号:", row_spin)
        col_spin = QSpinBox()
        col_spin.setRange(1, COL_COUNT)
        col_spin.setValue(self.table.currentIndex().column() + 1)
        layout.addRow("列号:", col_spin)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        layout.addRow(btns)
        if dlg.exec_() == QDialog.Accepted:
            r, c = row_spin.value() - 1, col_spin.value() - 1
            if 0 <= r < self.model.rowCount() and 0 <= c < COL_COUNT:
                self.table.setCurrentIndex(self.model.index(r, c))

    def _on_row_header_clicked(self, row):
        modifiers = QApplication.keyboardModifiers()
        sel = self.table.selectionModel()
        model = self.model
        if modifiers & Qt.ControlModifier:
            first_idx = model.index(row, 0)
            toggle_on = not sel.isSelected(first_idx)
            for c in range(COL_COUNT):
                sel.select(model.index(row, c),
                           sel.Select if toggle_on else sel.Deselect)
        elif modifiers & Qt.ShiftModifier:
            self.table.selectRow(row)
        else:
            self.table.clearSelection()
            self.table.selectRow(row)

    def _on_corner_clicked(self):
        self.table.selectAll()

    # ── 事件过滤 ──
    def eventFilter(self, obj, event):
        viewport = self.table.viewport()
        if obj is self.table:
            if event.type() == QEvent.KeyPress:
                return False
        if obj is viewport:
            if event.type() == QEvent.MouseButtonRelease:
                self._auto_scroll_timer.stop()
                self._dragging = False
            elif event.type() == QEvent.MouseButtonPress:
                if event.modifiers() & Qt.ControlModifier:
                    # Ctrl+单击：手动切换选择（统一处理，不再区分 widget/item）
                    pos = event.pos()
                    idx = self.table.indexAt(pos)
                    if idx.isValid():
                        sel = self.table.selectionModel()
                        if sel.isSelected(idx):
                            sel.select(idx, sel.Deselect)
                        else:
                            sel.select(idx, sel.Select)
                        return True
            elif event.type() == QEvent.Wheel:
                if event.modifiers() & Qt.ShiftModifier:
                    bar = self.table.horizontalScrollBar()
                    bar.setValue(bar.value() - event.angleDelta().y())
                    return True
            elif event.type() == QEvent.MouseMove:
                if event.buttons() & Qt.LeftButton:
                    self._dragging = True
                    vp_h = viewport.height()
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

    def _do_auto_scroll(self):
        bar = self.table.verticalScrollBar()
        bar.setValue(bar.value() + self._auto_scroll_dir * bar.singleStep())

    # ── 上下文菜单 ──
    def _show_context_menu(self, pos):
        idx = self.table.indexAt(pos)
        if not idx.isValid():
            return
        q = self.model.question_at_row(idx.row())
        if q is None:
            return
        menu = QMenu(self)
        a_view = menu.addAction("查看详情")
        a_edit = menu.addAction("编辑")
        a_reset = menu.addAction("重置错题计数")
        menu.addSeparator()
        a_del = menu.addAction("删除")
        action = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if action == a_edit:
            self.edit_requested.emit(q["id"])
        elif action == a_del:
            self._delete_question(q["id"])
        elif action == a_reset:
            models.reset_wrong_count(q["id"])
            self._do_search()
        elif action == a_view:
            self._show_detail(q)

    def _show_detail(self, q):
        detail = f"【题目】\n{q['question_text'] or '[图片]'}\n\n"
        detail += f"【答案】\n{q['answer_text'] or '[图片]'}\n\n"
        if q.get("notes"):
            detail += f"【备注】\n{q['notes']}\n\n"
        tags = models.get_question_tags(q["id"])
        if tags:
            detail += f"【标签】{'、'.join(t['name'] for t in tags)}\n\n"
        detail += f"【做错次数】{q['wrong_count']}"
        QMessageBox.information(self, "题目详情", detail)

    def _delete_question(self, qid):
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这道题目吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        images = models.get_question_images(qid)
        for img in images:
            if os.path.exists(img["image_path"]):
                os.remove(img["image_path"])
        models.delete_question(qid)
        self._do_search()

    # ── 批量操作 ──
    def _get_selected_or_all(self):
        selected = self._selected_ids
        if selected:
            return [q for q in self.all_questions if q["id"] in selected]
        return self.all_questions

    def _batch_move_category(self):
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
        all_cats = models.get_all_categories()
        new_id = next((c["id"] for c in all_cats if c["name"] == name.strip()), None)
        if new_id is None:
            return
        models.batch_set_category([q["id"] for q in to_edit], new_id)
        QMessageBox.information(
            self, "完成",
            f"已创建分类「{name.strip()}」并将 {len(to_edit)} 道题目移入。")
        self._refresh_filters()
        self._do_search()

    def _batch_add_tags(self):
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
        presets = ['#E74C3C', '#E67E22', '#F1C40F', '#2ECC71', '#1ABC9C',
                   '#3498DB', '#9B59B6', '#E91E63', '#795548', '#95A5A6']
        preset_row = QHBoxLayout()
        preset_row.setSpacing(4)
        for pc in presets:
            pb = PushButton()
            pb.setFixedSize(24, 24)
            pb.setCursor(Qt.PointingHandCursor)
            pb.setStyleSheet(
                f"background-color: {pc}; border: 1px solid #999; border-radius: 12px;")
            pb.clicked.connect(
                lambda checked, c=pc, cb=color_btn, nc=new_color:
                nc.__setitem__(0, c) or cb.setStyleSheet(
                    f"background-color: {c}; border: 1px solid #999; border-radius: 4px;"))
            preset_row.addWidget(pb)
        layout.addLayout(preset_row)

        def pick_color():
            c = QColorDialog.getColor()
            if c.isValid():
                new_color[0] = c.name()
                color_btn.setStyleSheet(
                    f"background-color: {c.name()}; border: 1px solid #999; border-radius: 4px;")
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
                for t in models.get_all_tags():
                    if t["name"] == new_name:
                        tag_ids.append(t["id"])
                        break
        if not tag_ids:
            return
        models.batch_set_tags([q["id"] for q in to_edit], tag_ids)
        QMessageBox.information(self, "完成", f"已为 {len(to_edit)} 道题目添加标签。")
        self._do_search()

    def _export_questions(self):
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
            f"将导出 {label} 题目。\n导出格式为包含 index.html 和图片的文件夹。\n确认继续？",
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
            success, result = export_questions(to_export, parent_dir, on_progress)
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

    # ── 分类/标签管理 ──
    def _refresh_filters(self):
        self._refreshing = True
        self.cat_filter.blockSignals(True)
        self.tag_filter.blockSignals(True)
        try:
            self.cat_filter.clear()
            self.cat_filter.addItem("全部分类", userData=None)
            self.cat_filter.addItem("★ 星标收藏夹", userData=-1)
            self.cat_filter.addItem("✗ 错题集", userData=-2)
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
        if self.cat_filter.count() > 0:
            self.cat_filter.setCurrentIndex(0)
        self.cat_filter.blockSignals(False)
        self.tag_filter.blockSignals(False)
        self._refreshing = False
        self._update_cat_btns()
        self.tag_filter.setContextMenuPolicy(Qt.CustomContextMenu)
        try:
            self.tag_filter.customContextMenuRequested.disconnect()
        except Exception:
            pass
        self.tag_filter.customContextMenuRequested.connect(self._on_tag_context_menu)

    def _update_cat_btns(self):
        cat_id = self.cat_filter.currentData()
        show = cat_id is not None and cat_id > 0
        self.cat_rename_btn.setVisible(show)
        self.cat_del_btn.setVisible(show)

    def _rename_category(self):
        cat_id = self.cat_filter.currentData()
        if not cat_id or cat_id <= 0:
            return
        name, ok = QInputDialog.getText(self, "重命名分类", "新名称：",
                                         text=self.cat_filter.currentText())
        if ok and name.strip():
            models.rename_category(cat_id, name.strip())
            self._refresh_filters()
            self._do_search()

    def _delete_category(self):
        cat_id = self.cat_filter.currentData()
        if not cat_id or cat_id <= 0:
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除分类「{self.cat_filter.currentText()}」吗？\n该分类下的题目将变为未分类。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            models.delete_category(cat_id)
            self._refresh_filters()
            self._do_search()

    def _on_tag_context_menu(self, pos):
        idx = self.tag_filter.currentIndex()
        tag_id = self.tag_filter.itemData(idx) if idx >= 0 else None
        if not tag_id:
            return
        menu = QMenu(self)
        menu.addAction("编辑标签", lambda: self._safe_edit_tag(tag_id))
        menu.addAction("删除标签", lambda: self._delete_tag(tag_id))
        menu.exec_(self.tag_filter.mapToGlobal(pos))

    def _safe_edit_tag(self, tag_id):
        try:
            self._edit_tag_dialog(tag_id)
        except Exception:
            pass

    def _edit_tag_dialog(self, tag_id):
        all_tags = models.get_all_tags()
        tag_info = next((t for t in all_tags if t["id"] == tag_id), None)
        if tag_info is None:
            return
        self._show_tag_editor(tag_id, tag_info["name"],
                              tag_info.get("color", "#4A90D9"))

    def _show_tag_editor(self, tag_id, tag_name, tag_color):
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
        cb.setStyleSheet(
            f"background-color: {cur[0]}; border:1px solid #999; border-radius:4px;")

        def epc():
            c = QColorDialog.getColor()
            if c.isValid():
                cur[0] = c.name()
                cb.setStyleSheet(
                    f"background-color:{c.name()}; border:1px solid #999; border-radius:4px;")
        cb.clicked.connect(epc)
        cr.addWidget(cb)
        dl.addLayout(cr)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        dl.addWidget(btns)
        if dlg.exec_() == QDialog.Accepted:
            nn = ne.text().strip()
            if nn and (nn != tag_name or cur[0] != tag_color):
                models.update_tag(tag_id, nn, cur[0])
                self._refresh_filters()
                self._do_search()

    def _delete_tag(self, tag_id):
        reply = QMessageBox.question(
            self, "确认删除", "确定要删除此标签吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            models.delete_tag(tag_id)
            self._refresh_filters()
            self._do_search()

    # ── 生命周期 ──
    def on_shown(self):
        self._refresh_filters()
        self._do_search()
        QTimer.singleShot(100, self.table.resizeRowsToContents)

    def update_dynamic_styles(self):
        self._refresh_table()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.table.resizeRowsToContents()

"""
Add Question Panel
==================

This module provides the "Add Question" (and edit question) user interface
for the Luti flashcard/quiz application.  The panel includes:

- **Category selector** with the ability to create new categories on the fly.
- **Question / Answer / Notes fields** each supporting:
  - Rich text editing via QTextEdit.
  - Voice input (speech-to-text) via SpeechService.
  - Image insertion with preview thumbnails.
  - Temporary and persisted image tracking so images survive form edits.
- **Tag editor** with inline chip-style display; tags are created by typing
  a name and pressing Enter.
- **Save** button that persists the question, its images and tag associations
  to the database.
- **Cancel edit** button (visible only when editing an existing question) that
  clears the form and returns to "new question" mode.
- **Keyboard shortcut** Ctrl+Return in any text field triggers save.

The panel can operate in two modes:
  1. **New-question mode**  – all fields empty, ``editing_id`` is ``None``.
  2. **Edit mode**          – populated via ``load_question(qid)``, cancel
     button visible, updated records replace the existing database row.

Helper classes ``TagChip`` and ``ImagePreview`` provide self-contained
removable widgets used inside the form.
"""

import os, tempfile
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFileDialog, QMessageBox, QInputDialog, QGridLayout,
    QApplication, QGraphicsOpacityEffect,
    QTextEdit, QFrame,  # ImageTextEdit 基类 + QFrame.NoFrame
)
from PyQt5.QtCore import Qt, pyqtSignal, QEvent, QMimeData, QTimer, QPropertyAnimation
from PyQt5.QtGui import QPixmap, QKeyEvent, QFontMetrics, QImage, QDragEnterEvent, QDropEvent
from qfluentwidgets import (
    PrimaryPushButton, PushButton, TransparentPushButton,
    ComboBox, LineEdit, CardWidget, SmoothScrollArea,
    InfoBar, InfoBarPosition,
)
from database import models
from services.image_service import save_image, delete_image
from services.speech_service import SpeechService
from config import IMAGE_DIR, AppSettings


# ---------------------------------------------------------------------------
#  Helper widgets
# ---------------------------------------------------------------------------

class TagChip(QFrame):
    """A small rounded "chip" widget displaying a tag name with a close button.

    Emits ``removed`` (carrying the tag's database ID) when the close button
    is clicked.  Used inside the tag container of ``AddQuestionPanel``.
    """
    removed = pyqtSignal(int)

    def __init__(self, tag_id, tag_name):
        """Initialise the chip.

        Args:
            tag_id (int): Database ID of the tag.
            tag_name (str): Display name of the tag.
        """
        super().__init__()
        self.tag_id = tag_id
        self.setObjectName("tagChip")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 4, 3)
        layout.setSpacing(4)

        label = QLabel(tag_name)
        label.setObjectName("tagLabel")
        layout.addWidget(label)

        close_btn = PushButton("x")
        close_btn.setFixedSize(18, 18)
        close_btn.setStyleSheet(
            "QPushButton { border: none; color: #4A90D9; font-size: 12px; font-weight: bold; background: transparent; }"
            "QPushButton:hover { color: #FF4D4F; }"
        )
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(lambda: self.removed.emit(self.tag_id))
        layout.addWidget(close_btn)


class ImageTextEdit(QTextEdit):
    """支持拖入图片文件和粘贴剪贴板图片的文本编辑框。

    拖入图片文件或 Ctrl+V 粘贴剪贴板中的图片时，发出 image_added 信号。
    """

    image_added = pyqtSignal(str, str)  # (file_path, field_type)

    def __init__(self, field_type, parent=None):
        super().__init__(parent)
        self._field_type = field_type
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if self._has_image_urls(event.mimeData()):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if self._is_image(path):
                self.image_added.emit(path, self._field_type)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def insertFromMimeData(self, source: QMimeData):
        """拦截粘贴操作：若剪贴板含图片则保存并发出信号"""
        if source.hasImage():
            img = source.imageData()
            if isinstance(img, QImage) and not img.isNull():
                tmp = os.path.join(tempfile.gettempdir(),
                                   f"luti_paste_{id(self)}_{os.urandom(4).hex()}.png")
                img.save(tmp)
                self.image_added.emit(tmp, self._field_type)
                return
        if source.hasUrls():
            for url in source.urls():
                path = url.toLocalFile()
                if self._is_image(path):
                    self.image_added.emit(path, self._field_type)
                    return
        super().insertFromMimeData(source)

    def _has_image_urls(self, mime):
        if mime.hasUrls():
            return any(self._is_image(u.toLocalFile()) for u in mime.urls())
        return False

    @staticmethod
    def _is_image(path):
        return path.lower().endswith(
            ('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico'))


class ImagePreview(QFrame):
    """图片预览控件：右下角拖拽调整大小，松开后自动保存缩放后的图片。

    Bottom-right corner of the *image* (not the frame) can be dragged to resize.
    On mouse release the resized pixmap is saved back to disk.
    """
    removed = pyqtSignal()

    def __init__(self, image_path):
        super().__init__()
        self.image_path = image_path
        self.setObjectName("card")
        self.setMouseTracking(True)
        self._base_pixmap = QPixmap(image_path)        # 原始图像，不改动
        self._display_w = min(300, self._base_pixmap.width())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self._img_label = QLabel()
        self._img_label.setMouseTracking(True)
        self._render_pixmap()
        self._img_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._img_label)

        btn_row = QHBoxLayout()
        remove_btn = PushButton("移除图片")
        remove_btn.setObjectName("dangerBtn")
        remove_btn.clicked.connect(self.removed.emit)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._resizing = False
        self._resize_start = None
        self._start_w = 0

    def _render_pixmap(self):
        w = self._display_w
        pixmap = self._base_pixmap.scaledToWidth(w, Qt.SmoothTransformation)
        self._img_label.setPixmap(pixmap)
        self._img_label.setFixedWidth(w + 6)
        self.setMinimumHeight(pixmap.height() + 60)

    def _in_handle(self, pos):
        """判断鼠标是否在图片右下角 20×20 区域内"""
        local = self._img_label.mapFrom(self, pos)
        return (local.x() > self._img_label.width() - 20 and
                local.y() > self._img_label.height() - 20 and
                local.x() >= 0 and local.y() >= 0)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._in_handle(event.pos()):
            self._resizing = True
            self._resize_start = event.globalPos()
            self._start_w = self._display_w
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            dx = event.globalPos().x() - self._resize_start.x()
            self._display_w = max(80, self._start_w + dx)
            self._render_pixmap()
            event.accept()
            return
        if self._in_handle(event.pos()):
            self._img_label.setCursor(Qt.SizeFDiagCursor)
        else:
            self._img_label.setCursor(Qt.ArrowCursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resizing:
            self._resizing = False
            # 将缩放后的图像保存到磁盘，后续显示以此为准
            resized = self._base_pixmap.scaledToWidth(
                self._display_w, Qt.SmoothTransformation)
            resized.save(self.image_path)
            self._base_pixmap = QPixmap(self.image_path)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
#  Main panel
# ---------------------------------------------------------------------------

class AddQuestionPanel(QWidget):
    """The main form widget for creating or editing a question.

    For styling purposes the form uses QSS object names (see style.qss for
    ``#pageTitle``, ``#card``, ``#primaryBtn``,  ``#secondaryBtn``,
    ``#smallBtn``, ``#dangerBtn``, ``#tagChip``, ``#tagLabel``).
    """

    def __init__(self):
        """Create the panel instance.

        Initialises the speech service, internal tracking structures for images
        and tag widgets, then calls ``_setup_ui`` to build the widget tree.
        """
        super().__init__()
        self.speech = SpeechService()
        self.editing_id = None                      # None = new question; int = editing
        self.temp_images = {"question": [], "answer": [], "notes": []}   # new images not yet persisted
        self.saved_images = {"question": [], "answer": [], "notes": []}  # persisted images loaded from DB
        self.tag_widgets = []                       # list of TagChip instances currently shown
        self._setup_ui()

    # ------------------------------------------------------------------
    #  UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self):
        """Build the complete widget tree for the add-question form.

        Layout overview (top to bottom):
            1. Page title.
            2. **Category bar** – combo box + "new category" button.
            3. **Question field**  – QTextEdit + voice/image buttons + preview row.
            4. **Answer field**    – same structure.
            5. **Notes field**     – same structure.
            6. **Tag editor**      – line-edit + chip container.
            7. **Save / Cancel**   – action buttons at the bottom.

        The whole form is wrapped in a ``QScrollArea`` so it stays usable on
        small screens.
        """
        # ---- Scroll area wrapping the form ----
        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        scroll.setWidget(container)

        outer = QVBoxLayout(container)
        outer.setContentsMargins(30, 20, 30, 20)
        outer.setSpacing(16)

        # ---- Page title ----
        title = QLabel("录入题目")
        title.setObjectName("pageTitle")
        outer.addWidget(title)

        # ---- 分类 (category) bar ----
        cat_frame = CardWidget()
        cat_frame.setObjectName("card")
        cat_layout = QHBoxLayout(cat_frame)
        cat_layout.setContentsMargins(16, 12, 16, 12)

        cat_layout.addWidget(QLabel("分类："))
        self.category_combo = ComboBox()
        self.category_combo.setMinimumWidth(180)
        cat_layout.addWidget(self.category_combo)

        add_cat_btn = PushButton("+ 新建分类")
        add_cat_btn.setObjectName("smallBtn")
        add_cat_btn.clicked.connect(self._add_category)
        cat_layout.addWidget(add_cat_btn)
        cat_layout.addStretch()

        outer.addWidget(cat_frame)

        # ---- 题目 (question) field ----
        self.question_edit = ImageTextEdit("question")
        self.question_edit.setPlaceholderText("请输入题目内容...")
        self.question_edit.installEventFilter(self)
        self.question_edit.image_added.connect(self._add_image_from_path)
        outer.addWidget(self._make_field("题目内容", self.question_edit, "question"))

        # ---- 答案 (answer) field ----
        self.answer_edit = ImageTextEdit("answer")
        self.answer_edit.setPlaceholderText("请输入答案...")
        self.answer_edit.installEventFilter(self)
        self.answer_edit.image_added.connect(self._add_image_from_path)
        outer.addWidget(self._make_field("答案", self.answer_edit, "answer"))

        # ---- 备注 (notes) field ----
        self.notes_edit = ImageTextEdit("notes")
        self.notes_edit.setPlaceholderText("备注（可选）...")
        self.notes_edit.installEventFilter(self)
        self.notes_edit.image_added.connect(self._add_image_from_path)
        outer.addWidget(self._make_field("备注", self.notes_edit, "notes"))

        # ---- 标签 (tags) editor ----
        tag_frame = CardWidget()
        tag_frame.setObjectName("card")
        tag_inner = QVBoxLayout(tag_frame)
        tag_inner.setContentsMargins(16, 12, 16, 12)

        tag_header = QHBoxLayout()
        tag_header.addWidget(QLabel("标签："))
        self.tag_input = LineEdit()
        self.tag_input.setPlaceholderText("输入标签名后按回车添加...")
        self.tag_input.setMaximumWidth(250)
        self.tag_input.returnPressed.connect(self._add_tag_chip)
        self.tag_input.installEventFilter(self)
        tag_header.addWidget(self.tag_input)
        tag_header.addStretch()
        tag_inner.addLayout(tag_header)

        self.tags_container = QHBoxLayout()
        self.tags_container.setSpacing(6)
        # Trailing stretch so chips left-align.
        self.tags_container.addStretch()
        tag_inner.addLayout(self.tags_container)

        outer.addWidget(tag_frame)

        outer.addStretch()

        # ---- 顶层布局：滚动区 + 底部固定按钮 ----
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        main_layout.addWidget(scroll)

        # 底部按钮栏（在滚动区外面，始终固定）
        btn_bar = CardWidget()
        btn_bar.setStyleSheet("QFrame { background-color: {color_bg}; border-top: 1px solid #E0E6ED; }")
        btn_bar_layout = QHBoxLayout(btn_bar)
        btn_bar_layout.setContentsMargins(30, 12, 30, 12)

        self.cancel_btn = PushButton("取消编辑")
        self.cancel_btn.setObjectName("secondaryBtn")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_edit)
        btn_bar_layout.addWidget(self.cancel_btn)

        btn_bar_layout.addStretch()

        self.save_btn = PushButton("保存题目 (Ctrl+S)")
        self.save_btn.setObjectName("saveBtn")
        self.save_btn.setCursor(Qt.PointingHandCursor)
        self.save_btn.setFixedHeight(60)
        self.save_btn.setMinimumWidth(320)
        self.save_btn.setStyleSheet(
            "QPushButton#saveBtn {"
            "  background-color: #52C41A; color: #FFFFFF;"
            "  font-size: 28px; font-weight: bold;"
            "  border: none; border-radius: 10px; padding: 10px 40px;"
            "}"
            "QPushButton#saveBtn:hover { background-color: #45A818; }"
        )
        self.save_btn.clicked.connect(self._save_question)
        btn_bar_layout.addWidget(self.save_btn)

        btn_bar_layout.addStretch()
        main_layout.addWidget(btn_bar)

        self.update_input_heights()

    # ------------------------------------------------------------------
    #  Field factory
    # ------------------------------------------------------------------

    def _make_field(self, label_text, edit_widget, field_type):
        """Build a card-style form field with label, action buttons, and image preview area.

        The returned frame contains:
            - A header row: label (left), voice-input button, image-insert button (right).
            - The edit widget (QTextEdit) passed in.
            - A horizontal layout at the bottom where ``ImagePreview`` widgets
              are dynamically inserted/removed.

        A reference to the preview layout is stored as an attribute on ``self``
        named ``{field_type}_preview_layout`` so that ``_add_image`` and
        ``_clear_form`` can manipulate it later.

        Args:
            label_text (str):  Label text displayed before the colon (e.g. "题目内容").
            edit_widget (QTextEdit): The text-edit widget for this field.
            field_type (str): Key used to identify the field in ``temp_images``
                              and ``saved_images`` dicts ("question" / "answer" / "notes").

        Returns:
            QFrame: The fully assembled card frame.
        """
        frame = CardWidget()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        # Header: label + action buttons
        header = QHBoxLayout()
        header.addWidget(QLabel(label_text + "："))
        header.addStretch()

        voice_btn = PushButton("🎤 语音输入")
        voice_btn.setObjectName("smallBtn")
        voice_btn.clicked.connect(lambda: self._start_voice(edit_widget))
        header.addWidget(voice_btn)

        img_btn = PushButton("📷 插入图片")
        img_btn.setObjectName("smallBtn")
        img_btn.clicked.connect(lambda: self._add_image(field_type))
        header.addWidget(img_btn)

        layout.addLayout(header)
        layout.addWidget(edit_widget)

        # Image-preview row (stretch on end keeps previews left-aligned)
        preview_layout = QHBoxLayout()
        preview_layout.setSpacing(10)
        preview_layout.addStretch()
        layout.addLayout(preview_layout)

        # Stash a reference so other methods can find the layout by field_type
        setattr(self, f"{field_type}_preview_layout", preview_layout)

        return frame

    # ------------------------------------------------------------------
    #  Voice input
    # ------------------------------------------------------------------

    def _start_voice(self, edit_widget):
        """Start speech recognition and insert recognised text at the cursor.

        If the speech-to-text dependencies are not installed a warning dialog
        is shown with installation instructions.  Otherwise the speech service
        starts listening; when recognition completes the text is inserted into
        *edit_widget* at the current cursor position.

        Args:
            edit_widget (QTextEdit): The text-edit widget to insert text into.
        """
        if not self.speech.is_available():
            QMessageBox.warning(
                self, "提示",
                "语音识别功能需要安装依赖库。\n请在命令行运行：\npip install SpeechRecognition pyaudio"
            )
            return

        def on_result(text):
            """Callback: insert recognised text at cursor."""
            cursor = edit_widget.textCursor()
            cursor.insertText(text)
            edit_widget.setTextCursor(cursor)

        def on_error(msg):
            """Callback: show error dialog."""
            QMessageBox.warning(self, "语音识别", msg)

        self.speech.recognize(on_result, on_error)

    # ------------------------------------------------------------------
    #  Image handling
    # ------------------------------------------------------------------

    def _add_image(self, field_type):
        """Open a file dialog, copy the chosen image into the app's image
        directory, and display a preview thumbnail in the specified field.

        The image is tracked in ``temp_images`` (new question) or
        ``saved_images`` (editing mode) so that it survives form navigation
        and gets persisted on save.

        Args:
            field_type (str): "question", "answer", or "notes" – which field
                              the image belongs to.
        """
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "",
            "图片文件 (*.jpg *.jpeg *.png *.gif *.bmp *.webp);;所有文件 (*.*)"
        )
        if not file_path:
            return

        # Copy to app image directory and get the saved path
        q = AppSettings().image_quality
        saved_path, err = save_image(file_path, field_type, quality=q)
        if err:
            QMessageBox.warning(self, "错误", err)
            return

        # Build and wire up an ImagePreview widget
        preview = ImagePreview(saved_path)
        preview.removed.connect(lambda p=saved_path, ft=field_type, w=preview: self._remove_temp_image(p, ft, w))

        # Track the image depending on mode
        if self.editing_id:
            self.saved_images[field_type].append(saved_path)
        else:
            self.temp_images[field_type].append(saved_path)

        # Insert preview widget before the trailing stretch in the preview row
        layout = getattr(self, f"{field_type}_preview_layout")
        layout.insertWidget(layout.count() - 1, preview)

    def _add_image_from_path(self, file_path, field_type):
        """通过文件路径添加图片（拖入/粘贴），复用 _add_image 的保存+预览逻辑"""
        q = AppSettings().image_quality
        saved_path, err = save_image(file_path, field_type, quality=q)
        if err:
            QMessageBox.warning(self, "错误", err)
            return

        preview = ImagePreview(saved_path)
        preview.removed.connect(
            lambda p=saved_path, ft=field_type, w=preview: self._remove_temp_image(p, ft, w))

        if self.editing_id:
            self.saved_images[field_type].append(saved_path)
        else:
            self.temp_images[field_type].append(saved_path)

        layout = getattr(self, f"{field_type}_preview_layout")
        layout.insertWidget(layout.count() - 1, preview)

    def _remove_temp_image(self, path, field_type, widget):
        """Remove an image preview from the form and delete its file on disk.

        Called when the user clicks "移除图片" on an ``ImagePreview`` widget.
        Cleans up the in-memory tracking lists, removes the widget from the
        layout, and schedules it for deletion.

        Args:
            path (str): Absolute path to the image file.
            field_type (str): Which field the image belongs to.
            widget (ImagePreview): The preview widget to remove.
        """
        delete_image(path)
        if path in self.temp_images.get(field_type, []):
            self.temp_images[field_type].remove(path)
        if path in self.saved_images.get(field_type, []):
            self.saved_images[field_type].remove(path)
        widget.setParent(None)
        widget.deleteLater()

    # ------------------------------------------------------------------
    #  Category management
    # ------------------------------------------------------------------

    def _add_category(self):
        """Prompt the user for a new category name and add it to the database.

        On success the category combo box is refreshed and the new entry
        is selected.  On failure (e.g. duplicate) an error dialog is shown.
        """
        name, ok = QInputDialog.getText(self, "新建分类", "请输入分类名称：")
        if ok and name.strip():
            success, msg = models.add_category(name.strip())
            if success:
                self._refresh_categories()
                idx = self.category_combo.findText(name.strip())
                if idx >= 0:
                    self.category_combo.setCurrentIndex(idx)
            else:
                QMessageBox.warning(self, "错误", msg)

    def _refresh_categories(self):
        """Repopulate the category combo box from the database.

        The first entry is always "无分类" (no category) with data ``None``,
        followed by every category row in the database.
        """
        self.category_combo.clear()
        self.category_combo.addItem("无分类", None)
        for cat in models.get_all_categories():
            self.category_combo.addItem(cat["name"], cat["id"])

    # ------------------------------------------------------------------
    #  Tag management
    # ------------------------------------------------------------------

    def _add_tag_chip(self):
        """Create a tag from the text in the tag input and add a chip to the form.

        The tag is persisted to the database if it does not already exist
        (duplicates are handled silently by looking up the existing ID).
        If the tag is already shown as a chip it is not added again.
        After adding, the tag input is cleared so the user can type the next tag.
        """
        name = self.tag_input.text().strip()
        if not name:
            return

        # Attempt to insert; "UNIQUE" constraint failure is expected for dupes
        tag_id, err = models.add_tag(name)
        if err and "UNIQUE" not in err.upper():
            QMessageBox.warning(self, "错误", f"添加标签失败：{err}")
            return

        # If insert failed because of duplicate, look up the existing ID
        if tag_id is None:
            all_tags = models.get_all_tags()
            for t in all_tags:
                if t["name"] == name:
                    tag_id = t["id"]
                    break

        # Avoid showing the same tag twice
        for w in self.tag_widgets:
            if w.tag_id == tag_id:
                self.tag_input.clear()
                return

        chip = TagChip(tag_id, name)
        chip.removed.connect(self._remove_tag_chip)
        self.tag_widgets.append(chip)
        self.tags_container.insertWidget(self.tags_container.count() - 1, chip)
        self.tag_input.clear()

    def _remove_tag_chip(self, tag_id):
        """Remove a tag chip from the form (visual only – DB persistence happens on save).

        The tag is *not* deleted from the database; it is merely disassociated
        from this question when ``_save_question`` replaces the tag set.

        Args:
            tag_id (int): Database ID of the tag to remove from the chip list.
        """
        for w in self.tag_widgets:
            if w.tag_id == tag_id:
                self.tag_widgets.remove(w)
                w.setParent(None)
                w.deleteLater()
                break

    # ------------------------------------------------------------------
    #  Save / cancel
    # ------------------------------------------------------------------

    def _save_question(self):
        """Validate the form and persist the question to the database.

        Logic:
            - At least the question text **or** one question image is required.
            - In edit mode the existing row is updated; otherwise a new row is
              inserted.
            - Existing image associations are cleared and re-created from the
              union of ``temp_images`` and ``saved_images``.
            - Tag associations are fully replaced from the current chip set.
            - On success the form is cleared and a confirmation dialog appears.
        """
        q_text = self.question_edit.toPlainText().strip()
        a_text = self.answer_edit.toPlainText().strip()

        if not q_text and not self.temp_images["question"] and not self.saved_images["question"]:
            self._show_toast("请输入题目内容或插入题目图片", success=False)
            return

        cat_id = self.category_combo.currentData()

        # Insert or update the question row
        if self.editing_id:
            models.update_question(self.editing_id, q_text, a_text,
                                   self.notes_edit.toPlainText().strip(), cat_id)
            qid = self.editing_id
            models.delete_question_images(qid)
        else:
            qid = models.add_question(q_text, a_text,
                                      self.notes_edit.toPlainText().strip(), cat_id)

        # Save all image associations
        all_images = {k: v + self.saved_images.get(k, [])
                      for k, v in self.temp_images.items()}
        for img_type, paths in all_images.items():
            for p in paths:
                models.save_question_image(qid, p, img_type)

        # Save tag associations
        tag_ids = [w.tag_id for w in self.tag_widgets]
        models.save_question_tags(qid, tag_ids)

        self._clear_form()
        self._show_toast("题目保存成功")

    def _cancel_edit(self):
        """Cancel editing and clear the form, returning to new-question mode."""
        self._clear_form()

    def _clear_form(self):
        """Reset all form fields to their default empty state.

        Preserves the currently selected category so the user can quickly
        add another question in the same category.
        """
        # Remember the currently selected category before clearing
        saved_cat = self.category_combo.currentData()

        self.editing_id = None
        self.question_edit.clear()
        self.answer_edit.clear()
        self.notes_edit.clear()
        self.cancel_btn.setVisible(False)

        # Remove all image previews and clear tracking lists
        for field in ["question", "answer", "notes"]:
            self.temp_images[field] = []
            self.saved_images[field] = []
            layout = getattr(self, f"{field}_preview_layout")
            # Remove all children except the trailing stretch
            while layout.count() > 1:
                w = layout.takeAt(0).widget()
                if w:
                    w.setParent(None)
                    w.deleteLater()

        # Remove all tag chips
        for w in self.tag_widgets:
            w.setParent(None)
            w.deleteLater()
        self.tag_widgets.clear()

        # Refresh and restore category selection
        self._refresh_categories()

        if saved_cat is not None:
            for i in range(self.category_combo.count()):
                if self.category_combo.itemData(i) == saved_cat:
                    self.category_combo.setCurrentIndex(i)
                    break

    # ------------------------------------------------------------------
    #  Edit mode entry
    # ------------------------------------------------------------------

    def load_question(self, qid):
        """Populate the form with an existing question for editing.

        Resets the form, then loads the question text, answer, notes, category,
        images, and tags from the database.  Sets ``editing_id`` so that
        ``_save_question`` performs an UPDATE rather than INSERT.

        Args:
            qid (int): Database ID of the question to load.
        """
        self._clear_form()
        q = models.get_question(qid)
        if not q:
            return

        self.editing_id = qid
        self.question_edit.setText(q["question_text"])
        self.answer_edit.setText(q["answer_text"])
        self.notes_edit.setText(q.get("notes", ""))
        self.cancel_btn.setVisible(True)

        # Restore category
        self._refresh_categories()
        if q["category_id"]:
            for i in range(self.category_combo.count()):
                if self.category_combo.itemData(i) == q["category_id"]:
                    self.category_combo.setCurrentIndex(i)
                    break

        # Restore images (tracked in saved_images so they survive form edits)
        images = models.get_question_images(qid)
        for img in images:
            if os.path.exists(img["image_path"]):
                self.saved_images[img["image_type"]].append(img["image_path"])
                preview = ImagePreview(img["image_path"])
                preview.removed.connect(
                    lambda p=img["image_path"], ft=img["image_type"], w=preview: self._remove_temp_image(p, ft, w)
                )
                layout = getattr(self, f"{img['image_type']}_preview_layout")
                layout.insertWidget(layout.count() - 1, preview)

        # Restore tag chips
        tags = models.get_question_tags(qid)
        for t in tags:
            chip = TagChip(t["id"], t["name"])
            chip.removed.connect(self._remove_tag_chip)
            self.tag_widgets.append(chip)
            self.tags_container.insertWidget(self.tags_container.count() - 1, chip)

    # ------------------------------------------------------------------
    #  Misc helpers
    # ------------------------------------------------------------------

    def _show_toast(self, text, success=True):
        """使用 Fluent InfoBar 显示保存结果（右上角弹出，3秒自动消失）"""
        if success:
            InfoBar.success("保存成功", text, duration=3000, parent=self)
        else:
            InfoBar.error("提示", text, duration=3000, parent=self)

    def on_shown(self):
        """Called when the panel becomes visible (e.g. tab switch).

        Refreshes the category list so any changes made elsewhere are reflected.
        """
        self._refresh_categories()

    def eventFilter(self, obj, event):
        """Global event filter installed on all text-editing widgets.

        Catches **Ctrl+Return** key presses and triggers ``_save_question``
        as a keyboard shortcut.  All other events are passed through to the
        default handler.

        Args:
            obj: The QObject that received the event.
            event: The QEvent to filter.

        Returns:
            bool: ``True`` if the event was consumed, ``False`` otherwise.
        """
        if event.type() == QEvent.KeyPress:
            key_event = event
            ctrl = key_event.modifiers() & Qt.ControlModifier
            if (key_event.key() == Qt.Key_Return and ctrl) or \
               (key_event.key() == Qt.Key_S and ctrl):
                self._save_question()
                return True
        return super().eventFilter(obj, event)

    def update_input_heights(self):
        """Adjust the QTextEdit minimum/maximum heights based on user settings.

        Reads ``AppSettings.input_lines`` to determine the target number of
        visible lines, then computes pixel heights using the current font
        metrics.  Sets a minimum height of N lines and a maximum of 3xN lines
        so the editor auto-expands but does not become excessively tall.
        """
        settings = AppSettings()
        lines = settings.input_lines
        fm = QFontMetrics(self.question_edit.font())
        line_h = fm.lineSpacing()
        h = line_h * lines + 16

        for edit in [self.question_edit, self.answer_edit, self.notes_edit]:
            edit.setMinimumHeight(h)
            edit.setMaximumHeight(h * 3)

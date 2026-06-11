"""
题库管理面板 — QWebEngineView + Tabulator.js
JS→Python 通过 URL 拦截通信，Python→JS 通过 runJavaScript()
"""
import os, json, subprocess
from urllib.parse import unquote
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QMessageBox, QMenu, QApplication,
    QFileDialog, QProgressDialog, QInputDialog,
    QDialog, QCheckBox, QDialogButtonBox, QColorDialog,
)
from PyQt5.QtCore import Qt, pyqtSignal, QUrl
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEnginePage
from qfluentwidgets import (
    PushButton, ComboBox, LineEdit, CardWidget,
)
from database import models
from config import AppSettings
from services.export_service import export_questions

PAGE_SIZE = 20


class QuestionListPanel(QWidget):
    """题库管理面板：QWebEngineView + Tabulator.js"""

    edit_requested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.all_questions = []
        self.current_page = 0
        self._sort_col = -1
        self._sort_state = 0
        self._original_order = []
        self._persistent_selected_ids = set()
        self._expanded_answers = set()
        self._setup_ui()
        self._setup_webview()

    # ── UI ──
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 20)
        layout.setSpacing(16)

        title = QLabel("题库管理")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        # 搜索/筛选
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
        self.sort_btn.clicked.connect(lambda: self._show_sort_menu(
            self.sort_btn.mapToGlobal(self.sort_btn.rect().bottomLeft())))
        fl.addWidget(self.sort_btn)

        self.batch_btn = PushButton("选择操作 ▾")
        self.batch_btn.setObjectName("primaryBtn")
        self.batch_btn.setCursor(Qt.PointingHandCursor)
        self._batch_menu = QMenu(self)
        self._batch_menu.addAction("导出题库", self._export_questions)
        self._batch_menu.addAction("添加标签", self._batch_add_tags)
        self._batch_menu.addAction("添加到新分类", self._batch_move_category)
        self.batch_btn.clicked.connect(lambda: self._batch_menu.exec_(
            self.batch_btn.mapToGlobal(self.batch_btn.rect().bottomLeft())))
        fl.addWidget(self.batch_btn)
        layout.addWidget(filter_frame)

        # 统计栏
        top_bar = QHBoxLayout()
        self.stats_label = QLabel()
        self.stats_label.setObjectName("statusLabel")
        top_bar.addWidget(self.stats_label)
        top_bar.addStretch()
        layout.addLayout(top_bar)

        # WebView
        self.webview = QWebEngineView()
        self.webview.setMinimumHeight(400)
        layout.addWidget(self.webview)

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

    # ── WebView + JS Bridge ──
    def _setup_webview(self):
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "table.html")
        self.webview.load(QUrl.fromLocalFile(html_path))
        self._page = self.webview.page()

        # 拦截 py:// 协议实现 JS→Python 通信
        class BridgePage(QWebEnginePage):
            def acceptNavigationRequest(self, url, nav_type, is_main_frame):
                if url.scheme() == "py":
                    panel._handle_bridge(url)
                    return False
                return super().acceptNavigationRequest(url, nav_type, is_main_frame)

        panel = self
        self.webview.setPage(BridgePage(self._page.profile()))

    def _handle_bridge(self, url):
        """处理 JS 端的 pyCall()"""
        try:
            path = url.path()  # /call/encoded_json
            if path.startswith("/call/"):
                payload = url.path()[len("/call/"):]
                data = json.loads(unquote(payload))
                action = data.get("a")
                arg = data.get("d")
                self._do_action(action, arg)
        except Exception:
            pass

    def _do_action(self, action, arg):
        if action == "toggle_star":
            new_val = models.toggle_star(int(arg))
            for q in self.all_questions:
                if q["id"] == int(arg):
                    q["starred"] = new_val
                    break
        elif action == "expand_answer":
            self._expanded_answers.add(int(arg))
        elif action == "collapse_answer":
            self._expanded_answers.discard(int(arg))
        elif action == "edit_question":
            self.edit_requested.emit(int(arg))
        elif action == "delete_question":
            self._delete_question(int(arg))
        elif action == "edit_tag":
            self._safe_edit_tag(int(arg))
        elif action == "selection_changed":
            ids = set(json.loads(arg))
            self._persistent_selected_ids = ids
            self._update_stats()
        elif action == "selection_cleared":
            self._persistent_selected_ids.clear()
            self._update_stats()
        elif action == "row_context":
            q = next((x for x in self.all_questions if x["id"] == int(arg)), None)
            if q:
                self._show_row_context(q)

    def _update_stats(self):
        total = len(self.all_questions)
        count = len(self._persistent_selected_ids)
        if count:
            self.stats_label.setText(f"共 {total} 道题目 | 已选中 {count} 道")
        else:
            self.stats_label.setText(f"共 {total} 道题目")

    # ── 属性 ──
    @property
    def _selected_ids(self):
        return self._persistent_selected_ids

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
            self._push_data()

    def _make_cat_map(self):
        cm = {}
        for c in models.get_all_categories():
            cm[c["id"]] = c["name"]
        return cm

    def _push_data(self):
        total = len(self.all_questions)
        tp = self._total_pages()
        if self.current_page >= tp:
            self.current_page = tp - 1
        start = self.current_page * PAGE_SIZE
        end = min(start + PAGE_SIZE, total)
        page_items = self.all_questions[start:end]

        mode = AppSettings().image_display_mode
        cat_map = self._make_cat_map()
        rows = []
        for i, q in enumerate(page_items):
            imgs = models.get_question_images(q["id"])
            q_imgs = [x for x in imgs if x["image_type"] == "question"]
            a_imgs = [x for x in imgs if x["image_type"] == "answer"]
            tags = models.get_question_tags(q["id"])
            u = q.get("updated_at", "")
            if u and len(u) > 16:
                u = u[:10].replace("-", "/") + " " + u[11:19]
            rows.append({
                "id": q["id"], "idx": start + i + 1,
                "uid": q.get("uid", "") or "-",
                "starred": q.get("starred", 0),
                "question": q.get("question_text", ""),
                "q_img": q_imgs[0]["image_path"] if q_imgs else "",
                "img_mode": mode,
                "cat": cat_map.get(q.get("category_id"), ""),
                "tags": [{"id": t["id"], "name": t["name"],
                          "color": t.get("color", "#4A90D9")} for t in tags],
                "answer": q.get("answer_text", ""),
                "a_img": a_imgs[0]["image_path"] if a_imgs else "",
                "ans_expanded": q["id"] in self._expanded_answers,
                "notes": q.get("notes", ""),
                "wrong_count": q.get("wrong_count", 0),
                "updated_at": u or "-"})

        json_str = json.dumps(rows, ensure_ascii=False)
        json_str = json_str.replace("\\", "\\\\").replace("'", "\\'")
        self.webview.page().runJavaScript("loadData('" + json_str + "')")

        self._update_stats()
        self.page_label.setText(f"第 {self.current_page + 1} / {tp} 页")
        self.prev_btn.setEnabled(self.current_page > 0)
        self.next_btn.setEnabled(self.current_page < tp - 1)

    # ── 翻页 ──
    def _prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self._push_data()

    def _next_page(self):
        if self.current_page < self._total_pages() - 1:
            self.current_page += 1
            self._push_data()

    # ── 排序 ──
    SORT_KEYS = {
        "uid": lambda q: q.get("uid", ""),
        "starred": lambda q: q.get("starred", 0),
        "question": lambda q: q.get("question_text", ""),
        "cat": lambda q: q.get("category_id") or 0,
        "tags": lambda q: q.get("_tags_str", ""),
        "answer": lambda q: q.get("answer_text", ""),
        "notes": lambda q: q.get("notes", ""),
        "wrong_count": lambda q: q.get("wrong_count", 0),
        "updated_at": lambda q: q.get("updated_at", ""),
    }
    SORT_LABELS = [
        ("uid", "初始编号"), ("starred", "星标"), ("question", "题目"),
        ("cat", "分类"), ("tags", "标签"), ("answer", "答案"),
        ("notes", "备注"), ("wrong_count", "错次"), ("updated_at", "最近修改"),
    ]

    def _show_sort_menu(self, global_pos):
        menu = QMenu(self)
        menu.addAction("恢复默认顺序", lambda: self._apply_py_sort(None, 0))
        menu.addSeparator()
        for field, label in self.SORT_LABELS:
            menu.addAction(f"↑ {label} 升序", lambda f=field: self._apply_py_sort(f, 1))
            menu.addAction(f"↓ {label} 降序", lambda f=field: self._apply_py_sort(f, 2))
        menu.exec_(global_pos)

    def _apply_py_sort(self, field, state):
        if state == 0:
            self._sort_col = -1; self._sort_state = 0
            self.sort_btn.setText("排序 ▾")
            if self._original_order:
                self.all_questions = self._original_order[:]
        else:
            self._sort_col = 0; self._sort_state = state
            self.all_questions.sort(key=self.SORT_KEYS[field], reverse=(state == 2))
            self.sort_btn.setText(f"排序: {field} {'↑' if state == 1 else '↓'}")
        self.current_page = 0
        self._push_data()

    # ── 删除/右键 ──
    def _delete_question(self, qid):
        reply = QMessageBox.question(self, "确认删除",
            "确定要删除这道题目吗？此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes: return
        for img in models.get_question_images(qid):
            if os.path.exists(img["image_path"]): os.remove(img["image_path"])
        models.delete_question(qid)
        self._do_search()

    def _show_row_context(self, q):
        menu = QMenu(self)
        a_view = menu.addAction("查看详情")
        a_edit = menu.addAction("编辑")
        a_reset = menu.addAction("重置错题计数")
        menu.addSeparator()
        a_del = menu.addAction("删除")
        action = menu.exec_(self.cursor().pos())
        if action == a_edit: self.edit_requested.emit(q["id"])
        elif action == a_del: self._delete_question(q["id"])
        elif action == a_reset:
            models.reset_wrong_count(q["id"]); self._do_search()
        elif action == a_view: self._show_detail(q)

    def _show_detail(self, q):
        d = f"【题目】\n{q['question_text'] or '[图片]'}\n\n【答案】\n{q['answer_text'] or '[图片]'}\n\n"
        if q.get("notes"): d += f"【备注】\n{q['notes']}\n\n"
        tags = models.get_question_tags(q["id"])
        if tags: d += f"【标签】{'、'.join(t['name'] for t in tags)}\n\n"
        d += f"【做错次数】{q['wrong_count']}"
        QMessageBox.information(self, "题目详情", d)

    # ── 批量操作 ──
    def _get_selected_or_all(self):
        s = self._persistent_selected_ids
        return [q for q in self.all_questions if q["id"] in s] if s else self.all_questions

    def _batch_move_category(self):
        to_edit = self._get_selected_or_all()
        if not to_edit: return QMessageBox.warning(self, "提示", "未选中任何题目。")
        name, ok = QInputDialog.getText(self, "新建分类", "请输入新分类名称：")
        if not ok or not name.strip(): return
        s, msg = models.add_category(name.strip())
        if not s: return QMessageBox.warning(self, "错误", msg)
        ac = models.get_all_categories()
        nid = next((c["id"] for c in ac if c["name"] == name.strip()), None)
        if nid is None: return
        models.batch_set_category([q["id"] for q in to_edit], nid)
        QMessageBox.information(self, "完成", f"已创建分类「{name.strip()}」并将 {len(to_edit)} 道题目移入。")
        self._refresh_filters(); self._do_search()

    def _batch_add_tags(self):
        to_edit = self._get_selected_or_all()
        if not to_edit: return QMessageBox.warning(self, "提示", "未选中任何题目。")
        dlg = QDialog(self); dlg.setWindowTitle("添加标签"); dlg.setMinimumSize(360, 300)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("选择要添加的标签（可多选）："))
        all_tags = models.get_all_tags(); checks = []
        for tag in all_tags:
            cb = QCheckBox(tag["name"]); cb._tag_id = tag["id"]
            cb.setStyleSheet(f"QCheckBox {{ color: {tag.get('color', '#4A90D9')}; font-weight: bold; font-size: 14px; }}")
            checks.append(cb); layout.addWidget(cb)
        layout.addWidget(QLabel("—— 或创建新标签 ——"))
        row = QHBoxLayout(); row.addWidget(QLabel("名称:"))
        name_edit = LineEdit(); name_edit.setPlaceholderText("新标签名称"); row.addWidget(name_edit)
        row.addWidget(QLabel("颜色:")); color_btn = PushButton(); color_btn.setFixedSize(28, 28)
        color_btn.setStyleSheet("background-color: #4A90D9; border: 1px solid #999; border-radius: 4px;")
        color_btn.setCursor(Qt.PointingHandCursor); new_color = ['#4A90D9']
        presets = ['#E74C3C','#E67E22','#F1C40F','#2ECC71','#1ABC9C','#3498DB','#9B59B6','#E91E63','#795548','#95A5A6']
        pr = QHBoxLayout(); pr.setSpacing(4)
        for pc in presets:
            pb = PushButton(); pb.setFixedSize(24, 24); pb.setCursor(Qt.PointingHandCursor)
            pb.setStyleSheet(f"background-color: {pc}; border: 1px solid #999; border-radius: 12px;")
            pb.clicked.connect(lambda ch, c=pc, cb=color_btn, nc=new_color: nc.__setitem__(0, c) or cb.setStyleSheet(f"background-color: {c}; border: 1px solid #999; border-radius: 4px;"))
            pr.addWidget(pb)
        layout.addLayout(pr)
        def pc():
            c = QColorDialog.getColor()
            if c.isValid(): new_color[0] = c.name(); color_btn.setStyleSheet(f"background-color: {c.name()}; border: 1px solid #999; border-radius: 4px;")
        color_btn.clicked.connect(pc); row.addWidget(color_btn); layout.addLayout(row)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject); layout.addWidget(btns)
        if dlg.exec_() != QDialog.Accepted: return
        tag_ids = [cb._tag_id for cb in checks if cb.isChecked()]
        nn = name_edit.text().strip()
        if nn:
            tid, err = models.add_tag(nn, new_color[0])
            if tid: tag_ids.append(tid)
            elif err and "UNIQUE" not in err.upper():
                for t in models.get_all_tags():
                    if t["name"] == nn: tag_ids.append(t["id"]); break
        if not tag_ids: return
        models.batch_set_tags([q["id"] for q in to_edit], tag_ids)
        QMessageBox.information(self, "完成", f"已为 {len(to_edit)} 道题目添加标签。")
        self._do_search()

    def _export_questions(self):
        to_export = self._get_selected_or_all()
        if not to_export: return QMessageBox.warning(self, "提示", "当前没有题目可导出。")
        parent_dir = QFileDialog.getExistingDirectory(self, "选择导出位置")
        if not parent_dir: return
        total = len(to_export)
        label = f"已选中 {total} 道" if self._persistent_selected_ids else f"当前筛选共 {total} 道"
        reply = QMessageBox.question(self, "确认导出", f"将导出 {label} 题目。\n确认继续？", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes: return
        try:
            success, result = export_questions(to_export, parent_dir, None)
        except Exception as e:
            return QMessageBox.critical(self, "导出失败", str(e))
        if success:
            msg = QMessageBox(self); msg.setWindowTitle("导出成功"); msg.setText(f"已导出 {total} 道题目。")
            msg.setInformativeText(f"位置：{result}")
            ob = msg.addButton("打开文件夹", QMessageBox.AcceptRole); msg.addButton("关闭", QMessageBox.RejectRole)
            msg.exec_()
            if msg.clickedButton() == ob: subprocess.Popen(f'explorer "{result}"')
        else:
            QMessageBox.critical(self, "导出失败", str(result))

    # ── 分类/标签管理 ──
    def _refresh_filters(self):
        self._refreshing = True
        self.cat_filter.blockSignals(True); self.tag_filter.blockSignals(True)
        try:
            self.cat_filter.clear()
            self.cat_filter.addItem("全部分类", userData=None)
            self.cat_filter.addItem("★ 星标收藏夹", userData=-1)
            self.cat_filter.addItem("✗ 错题集", userData=-2)
            self.cat_filter.addItem("──────────"); self.cat_filter.setItemEnabled(3, False)
            for cat in models.get_all_categories():
                self.cat_filter.addItem(cat["name"], userData=cat["id"])
        finally: pass
        self.tag_filter.clear(); self.tag_filter.addItem("全部标签", userData=None)
        for tag in models.get_all_tags(): self.tag_filter.addItem(tag["name"], userData=tag["id"])
        if self.cat_filter.count() > 0: self.cat_filter.setCurrentIndex(0)
        self.cat_filter.blockSignals(False); self.tag_filter.blockSignals(False)
        self._refreshing = False; self._update_cat_btns()
        self.tag_filter.setContextMenuPolicy(Qt.CustomContextMenu)
        try: self.tag_filter.customContextMenuRequested.disconnect()
        except Exception: pass
        self.tag_filter.customContextMenuRequested.connect(self._on_tag_context_menu)

    def _update_cat_btns(self):
        cat_id = self.cat_filter.currentData(); show = cat_id is not None and cat_id > 0
        self.cat_rename_btn.setVisible(show); self.cat_del_btn.setVisible(show)

    def _rename_category(self):
        cat_id = self.cat_filter.currentData()
        if not cat_id or cat_id <= 0: return
        name, ok = QInputDialog.getText(self, "重命名分类", "新名称：", text=self.cat_filter.currentText())
        if ok and name.strip():
            models.rename_category(cat_id, name.strip()); self._refresh_filters(); self._do_search()

    def _delete_category(self):
        cat_id = self.cat_filter.currentData()
        if not cat_id or cat_id <= 0: return
        r = QMessageBox.question(self, "确认删除", f"确定要删除分类「{self.cat_filter.currentText()}」吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes: models.delete_category(cat_id); self._refresh_filters(); self._do_search()

    def _on_tag_context_menu(self, pos):
        idx = self.tag_filter.currentIndex(); tag_id = self.tag_filter.itemData(idx) if idx >= 0 else None
        if not tag_id: return
        menu = QMenu(self)
        menu.addAction("编辑标签", lambda: self._safe_edit_tag(tag_id))
        menu.addAction("删除标签", lambda: self._delete_tag(tag_id))
        menu.exec_(self.tag_filter.mapToGlobal(pos))

    def _safe_edit_tag(self, tag_id):
        try: self._edit_tag_dialog(tag_id)
        except Exception: pass

    def _edit_tag_dialog(self, tag_id):
        at = models.get_all_tags(); ti = next((t for t in at if t["id"] == tag_id), None)
        if ti is None: return
        self._show_tag_editor(tag_id, ti["name"], ti.get("color", "#4A90D9"))

    def _show_tag_editor(self, tag_id, tag_name, tag_color):
        dlg = QDialog(self); dlg.setWindowTitle("编辑标签"); dlg.setMinimumSize(320, 150)
        dl = QVBoxLayout(dlg); nr = QHBoxLayout(); nr.addWidget(QLabel("名称:"))
        ne = LineEdit(tag_name); nr.addWidget(ne); dl.addLayout(nr)
        cr = QHBoxLayout(); cr.addWidget(QLabel("颜色:")); cb = PushButton(); cb.setFixedSize(28, 28)
        cur = [tag_color]; cb.setStyleSheet(f"background-color: {cur[0]}; border:1px solid #999; border-radius:4px;")
        def epc():
            c = QColorDialog.getColor()
            if c.isValid(): cur[0] = c.name(); cb.setStyleSheet(f"background-color:{c.name()}; border:1px solid #999; border-radius:4px;")
        cb.clicked.connect(epc); cr.addWidget(cb); dl.addLayout(cr)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject); dl.addWidget(btns)
        if dlg.exec_() == QDialog.Accepted:
            nn = ne.text().strip()
            if nn and (nn != tag_name or cur[0] != tag_color):
                models.update_tag(tag_id, nn, cur[0]); self._refresh_filters(); self._do_search()

    def _delete_tag(self, tag_id):
        r = QMessageBox.question(self, "确认删除", "确定要删除此标签吗？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes: models.delete_tag(tag_id); self._refresh_filters(); self._do_search()

    # ── 生命周期 ──
    def on_shown(self):
        self._persistent_selected_ids.clear()
        self._refresh_filters()
        self._do_search()

    def update_dynamic_styles(self):
        self.webview.page().runJavaScript(f"setFontScale({AppSettings().font_scale})")

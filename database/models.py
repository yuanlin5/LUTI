"""
=============================================================================
 数据访问层 —— 所有数据库的增删改查操作
=============================================================================
 本文件提供对 categories、tags、questions、question_images、
 question_tags、exams、exam_answers 七张表的完整 CRUD 接口。
 所有函数均使用 get_connection() 获取数据库连接并在操作后关闭。
=============================================================================
"""

from database.db_manager import get_connection


# ============================================================================
# 分类操作
# ============================================================================

def get_all_categories():
    """获取所有分类列表，按 ID 排序"""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM categories ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_category(name):
    """
    添加一个新分类。
    返回 (True, "添加成功") 或 (False, 错误信息)
    """
    conn = get_connection()
    try:
        conn.execute("INSERT INTO categories (name) VALUES (?)", (name.strip(),))
        conn.commit()
        return True, "添加成功"
    except Exception as e:
        err = str(e)
        if "UNIQUE" in err.upper():
            return False, f"分类「{name.strip()}」已存在，请使用其他名称。"
        return False, f"添加分类失败：{err}"
    finally:
        conn.close()


def rename_category(cat_id, new_name):
    """重命名分类。返回 True/False"""
    conn = get_connection()
    try:
        conn.execute("UPDATE categories SET name = ? WHERE id = ?", (new_name.strip(), cat_id))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def delete_category(cat_id):
    """删除指定分类（关联的题目 category_id 会自动设为 NULL）"""
    conn = get_connection()
    conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    conn.commit()
    conn.close()


# ============================================================================
# 标签操作
# ============================================================================

def get_all_tags():
    """获取所有标签列表，按 ID 排序"""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM tags ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_tag(name, color='#4A90D9'):
    """
    添加一个新标签。如果同名标签已存在，返回已有的 ID。
    返回 (tag_id, None) 成功，或 (None, 错误信息) 失败
    """
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tags (name, color) VALUES (?, ?)",
            (name.strip(), color))
        conn.commit()
        return cur.lastrowid, None
    except Exception as e:
        err = str(e)
        if "UNIQUE" in err.upper():
            return None, f"标签「{name.strip()}」已存在。"
        return None, f"添加标签失败：{err}"
    finally:
        conn.close()


def batch_set_tags(question_ids, tag_ids):
    """批量为题目添加标签（不覆盖已有标签）"""
    conn = get_connection()
    for qid in question_ids:
        for tid in tag_ids:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO question_tags (question_id, tag_id)"
                    " VALUES (?, ?)", (qid, tid))
            except Exception:
                pass
    conn.commit()
    conn.close()


def batch_set_category(question_ids, category_id):
    """批量设置题目的分类"""
    conn = get_connection()
    conn.executemany(
        "UPDATE questions SET category_id = ?, updated_at = CURRENT_TIMESTAMP"
        " WHERE id = ?",
        [(category_id, qid) for qid in question_ids])
    conn.commit()
    conn.close()


def delete_tag(tag_id):
    """删除指定标签（关联数据自动删除）"""
    conn = get_connection()
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    conn.commit()
    conn.close()


# ============================================================================
# 题目操作
# ============================================================================

def add_question(question_text, answer_text, notes, category_id):
    """
    新增一道题目。category_id 可为 None。
    自动生成不可变的初始编号 (uid)。返回新题目的 ID。
    """
    from datetime import datetime
    conn = get_connection()
    now = datetime.now()
    prefix = now.strftime("%Y%m%d%H%M%S")
    # 确保同一秒内不重复
    seq = 1
    while True:
        uid = f"{prefix}{seq:02d}"
        existing = conn.execute(
            "SELECT id FROM questions WHERE uid = ?", (uid,)).fetchone()
        if not existing:
            break
        seq += 1
    cur = conn.execute(
        """INSERT INTO questions (question_text, answer_text, notes, category_id, uid)
           VALUES (?, ?, ?, ?, ?)""",
        (question_text, answer_text, notes, category_id, uid),
    )
    conn.commit()
    qid = cur.lastrowid
    conn.close()
    return qid


def update_question(qid, question_text, answer_text, notes, category_id):
    """更新已有题目的内容和分类（updated_at 自动更新）"""
    conn = get_connection()
    conn.execute(
        """UPDATE questions
           SET question_text=?, answer_text=?, notes=?, category_id=?,
               updated_at=CURRENT_TIMESTAMP
           WHERE id=?""",
        (question_text, answer_text, notes, category_id, qid),
    )
    conn.commit()
    conn.close()


def delete_question(qid):
    """删除一道题目（关联的图片和标签也会级联删除）"""
    conn = get_connection()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM questions WHERE id = ?", (qid,))
    conn.commit()
    conn.close()


def get_question(qid):
    """获取单道题目的完整信息，不存在返回 None"""
    conn = get_connection()
    row = conn.execute("SELECT * FROM questions WHERE id = ?", (qid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def search_questions(keyword="", category_id=None, tag_id=None):
    """
    搜索题目——支持关键词、分类、标签三种筛选条件组合。
    参数均可选（传 None 表示不过滤），结果按更新时间倒序排列。
    """
    conn = get_connection()
    query = "SELECT DISTINCT q.* FROM questions q"
    params = []
    joins = []
    conditions = []

    # 按标签筛选（需要 JOIN question_tags 表）
    if tag_id is not None:
        joins.append("JOIN question_tags qt ON q.id = qt.question_id")
        conditions.append("qt.tag_id = ?")
        params.append(tag_id)

    # 按关键词搜索（在题目、答案、备注中模糊匹配）
    if keyword:
        conditions.append(
            "(q.question_text LIKE ? OR q.answer_text LIKE ? OR q.notes LIKE ?)"
        )
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])

    # 按分类筛选
    if category_id is not None:
        conditions.append("q.category_id = ?")
        params.append(category_id)

    if joins:
        query += " " + " ".join(joins)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY q.updated_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def increment_wrong_count(qid):
    """某道题做错了，做错次数 +1"""
    conn = get_connection()
    conn.execute(
        "UPDATE questions SET wrong_count = wrong_count + 1 WHERE id = ?", (qid,)
    )
    conn.commit()
    conn.close()


def reset_wrong_count(qid):
    """将某道题的做错次数重置为 0（表示已掌握）"""
    conn = get_connection()
    conn.execute("UPDATE questions SET wrong_count = 0 WHERE id = ?", (qid,))
    conn.commit()
    conn.close()


def toggle_star(qid):
    """切换星标状态，返回新状态 (0 或 1)"""
    conn = get_connection()
    cur = conn.execute("SELECT starred FROM questions WHERE id = ?", (qid,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        return 0
    new_val = 0 if row[0] else 1
    conn.execute("UPDATE questions SET starred = ? WHERE id = ?", (new_val, qid))
    conn.commit()
    conn.close()
    return new_val


def get_starred_questions(keyword="", category_id=None):
    """获取星标收藏夹——查询所有 starred = 1 的题目"""
    conn = get_connection()
    query = """
        SELECT q.id, q.question_text, q.answer_text, q.notes,
               q.category_id, q.wrong_count, q.starred,
               q.created_at, q.updated_at
        FROM questions q
        WHERE q.starred = 1
    """
    params = []
    if keyword:
        query += " AND (q.question_text LIKE ? OR q.answer_text LIKE ? OR q.notes LIKE ?)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    if category_id is not None:
        query += " AND q.category_id = ?"
        params.append(category_id)
    query += " ORDER BY q.updated_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_wrong_questions(keyword="", category_id=None):
    """
    获取错题集——查询所有 wrong_count > 0 的题目。
    支持关键词搜索和分类筛选，按做错次数降序排列（错得多的排前面）。
    """
    conn = get_connection()
    query = "SELECT * FROM questions WHERE wrong_count > 0"
    params = []

    if keyword:
        query += " AND (question_text LIKE ? OR answer_text LIKE ?)"
        kw = f"%{keyword}%"
        params.extend([kw, kw])
    if category_id is not None:
        query += " AND category_id = ?"
        params.append(category_id)

    query += " ORDER BY wrong_count DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================================
# 题目图片操作
# ============================================================================

def save_question_image(question_id, image_path, image_type):
    """
    保存题目与图片的关联。
    image_type 必须是 'question'、'answer' 或 'notes' 之一。
    """
    conn = get_connection()
    conn.execute(
        "INSERT INTO question_images (question_id, image_path, image_type) VALUES (?, ?, ?)",
        (question_id, image_path, image_type),
    )
    conn.commit()
    conn.close()


def get_question_images(question_id):
    """获取某道题目的所有关联图片"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM question_images WHERE question_id = ?", (question_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_question_images(question_id):
    """删除某道题目的所有图片关联（编辑题目时先删后重建）"""
    conn = get_connection()
    conn.execute("DELETE FROM question_images WHERE question_id = ?", (question_id,))
    conn.commit()
    conn.close()


# ============================================================================
# 题目标签关联操作
# ============================================================================

def save_question_tags(question_id, tag_ids):
    """
    保存题目与标签的关联。
    先删除旧的关联，再批量插入新的关联（tag_ids 是标签 ID 的列表）。
    """
    conn = get_connection()
    conn.execute("DELETE FROM question_tags WHERE question_id = ?", (question_id,))
    for tid in tag_ids:
        conn.execute(
            "INSERT OR IGNORE INTO question_tags (question_id, tag_id) VALUES (?, ?)",
            (question_id, tid),
        )
    conn.commit()
    conn.close()


def get_question_tags(question_id):
    """获取某道题目的所有关联标签"""
    conn = get_connection()
    rows = conn.execute(
        """SELECT t.* FROM tags t
           JOIN question_tags qt ON t.id = qt.tag_id
           WHERE qt.question_id = ?""",
        (question_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================================
# 考试记录操作
# ============================================================================

def create_exam(title, total):
    """
    创建一次新的考试记录。
    title 自动生成（如"考试 05-28 14:30"），total 为题目总数。
    返回考试 ID。
    """
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO exams (title, total_questions) VALUES (?, ?)", (title, total)
    )
    conn.commit()
    eid = cur.lastrowid
    conn.close()
    return eid


def finish_exam(eid, correct, wrong):
    """考试结束后更新正确数和错误数"""
    conn = get_connection()
    conn.execute(
        "UPDATE exams SET correct_count=?, wrong_count=? WHERE id=?",
        (correct, wrong, eid),
    )
    conn.commit()
    conn.close()


def save_exam_answer(exam_id, question_id, is_wrong):
    """
    记录一道题的答题结果。
    is_wrong = True 表示做错，False 表示做对。
    """
    conn = get_connection()
    conn.execute(
        "INSERT INTO exam_answers (exam_id, question_id, is_wrong) VALUES (?, ?, ?)",
        (exam_id, question_id, 1 if is_wrong else 0),
    )
    conn.commit()
    conn.close()

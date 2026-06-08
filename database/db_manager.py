"""
=============================================================================
 数据库连接与建表
=============================================================================
 负责管理 SQLite 数据库的连接和初始化建表。
 所有 SQL 表结构都定义在此文件的 init_db() 函数中。
=============================================================================
"""

import sqlite3
from config import DB_PATH


def get_connection():
    """
    获取数据库连接。
    每次调用返回新的连接对象，使用完毕后记得 conn.close()。

    关键配置：
      - PRAGMA foreign_keys = ON  : 启用外键约束（级联删除等）
      - row_factory = sqlite3.Row : 查询结果可用 dict(row) 转换为字典
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    初始化数据库——创建所有数据表（如果不存在）。
    程序启动时自动调用一次。

    数据库共 7 张表：
      categories     — 题目分类（数学、英语等）
      tags           — 标签（易错、重点等）
      questions      — 题目主表（包含问题、答案、备注、分类、做错次数）
      question_images— 题目关联的图片
      question_tags  — 题目与标签的多对多关联
      exams          — 考试记录
      exam_answers   — 考试中每道题的答题明细
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript('''
        -- ---------------------------------------------------------------
        -- 分类表：题目的归属类别
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 分类 ID（自增）
            name TEXT NOT NULL UNIQUE,               -- 分类名称（不可重复）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ---------------------------------------------------------------
        -- 标签表：题目的附加标签
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 标签 ID（自增）
            name TEXT NOT NULL UNIQUE,               -- 标签名称（不可重复）
            color TEXT DEFAULT '#4A90D9',            -- 标签颜色（hex）
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ---------------------------------------------------------------
        -- 题目主表：存储所有题目的核心信息
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 题目 ID（自增）
            question_text TEXT NOT NULL DEFAULT '',  -- 题目文字内容
            answer_text TEXT NOT NULL DEFAULT '',    -- 答案文字内容
            notes TEXT DEFAULT '',                   -- 备注（可选）
            category_id INTEGER,                     -- 所属分类 ID
            wrong_count INTEGER DEFAULT 0,           -- 历史做错次数
            starred INTEGER DEFAULT 0,               -- 星标 (0=未标, 1=已标)
            uid TEXT DEFAULT '',                     -- 初始编号 (年月日时分秒+序号)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
                -- 删除分类时，题目中的 category_id 自动设为 NULL
        );

        -- ---------------------------------------------------------------
        -- 题目图片表：每道题可在问题/答案/备注中插入多张图片
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS question_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 图片记录 ID
            question_id INTEGER NOT NULL,            -- 所属题目 ID
            image_path TEXT NOT NULL,                -- 图片文件路径
            image_type TEXT NOT NULL                 -- 图片类型：question/answer/notes
                CHECK(image_type IN ('question', 'answer', 'notes')),
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
                -- 删除题目时，关联图片记录自动删除
        );

        -- ---------------------------------------------------------------
        -- 题目标签关联表：题目和标签的多对多关系
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS question_tags (
            question_id INTEGER NOT NULL,            -- 题目 ID
            tag_id INTEGER NOT NULL,                 -- 标签 ID
            PRIMARY KEY (question_id, tag_id),       -- 联合主键，防止重复关联
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        );

        -- ---------------------------------------------------------------
        -- 考试记录表：每次组卷考试的汇总
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 考试 ID
            title TEXT,                              -- 考试标题（自动生成时间戳）
            total_questions INTEGER DEFAULT 0,       -- 试卷总题数
            correct_count INTEGER DEFAULT 0,         -- 做对的数量
            wrong_count INTEGER DEFAULT 0,           -- 做错的数量
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- ---------------------------------------------------------------
        -- 考试答题明细：记录每道题的判对/判错
        -- ---------------------------------------------------------------
        CREATE TABLE IF NOT EXISTS exam_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,   -- 记录 ID
            exam_id INTEGER NOT NULL,                -- 所属考试 ID
            question_id INTEGER NOT NULL,            -- 题目 ID
            is_wrong INTEGER DEFAULT 0,              -- 0=正确 1=错误
            answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
            FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
        );
    ''')

    # 为旧数据库添加 starred 列
    try:
        cursor.execute("ALTER TABLE questions ADD COLUMN starred INTEGER DEFAULT 0")
    except Exception:
        pass
    # 为旧数据库添加 color 列
    try:
        cursor.execute("ALTER TABLE tags ADD COLUMN color TEXT DEFAULT '#4A90D9'")
    except Exception:
        pass
    # 为旧数据库添加 uid 列
    try:
        cursor.execute("ALTER TABLE questions ADD COLUMN uid TEXT DEFAULT ''")
    except Exception:
        pass

    conn.commit()
    conn.close()

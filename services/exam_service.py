"""
=============================================================================
 考试服务 —— 组卷抽题与答题记录
=============================================================================
"""

import random
from database import models


def generate_exam_questions(total, category_id=None, tag_id=None):
    """
    从题库中随机抽取指定数量的题目组成试卷。

    参数：
      total       — 需要的题目数量
      category_id — 可选，限定分类（None 表示不限）
      tag_id      — 可选，限定标签（None 表示不限）

    返回：
      题目列表。如果题库中符合条件的题目不足 total 道，返回全部。
    """
    all_questions = models.search_questions(
        category_id=category_id, tag_id=tag_id
    )
    if len(all_questions) < total:
        total = len(all_questions)

    # random.sample 保证不重复抽取
    selected = random.sample(all_questions, total)
    return selected


def record_answer(exam_id, question_id, is_wrong):
    """
    记录一道题的答题结果。
    is_wrong=True 时，自动增加该题的做错次数。
    """
    models.save_exam_answer(exam_id, question_id, is_wrong)
    if is_wrong:
        models.increment_wrong_count(question_id)

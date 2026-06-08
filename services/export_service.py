"""
题库导出服务。

将题目列表导出为自包含的 HTML 文件夹（index.html + images/），
可在任意浏览器中双击打开浏览。
"""
import os, shutil, json
from datetime import datetime
from services.export_template import EXPORT_HTML
from database import models


def export_questions(questions, parent_dir, progress_callback=None):
    """导出题目到 HTML 文件夹。

    Args:
        questions: list[dict] — 题目列表（通常来自 search_questions）
        parent_dir: str — 导出文件夹的父目录
        progress_callback: callable(step, current, total) or None

    Returns:
        (True, export_folder_path) 或 (False, error_message)
    """
    if not questions:
        return False, "没有题目可导出"

    # 1. 收集数据
    _report(progress_callback, "收集题目数据...", 0, 1)
    enriched = _enrich_questions(questions)
    _report(progress_callback, "收集完成", 1, 1)

    # 2. 去重收集图片路径
    _report(progress_callback, "统计图片...", 0, 1)
    image_set = _collect_unique_images(enriched)
    _report(progress_callback, f"共 {len(image_set)} 张图片", 1, 1)

    # 3. 创建导出结构
    export_folder, images_dir = _create_export_structure(parent_dir)

    # 4. 复制图片
    copied = 0
    total_img = len(image_set)
    if total_img > 0:
        for i, src in enumerate(sorted(image_set)):
            try:
                if progress_callback and progress_callback(
                        "copying", i + 1, total_img):
                    return False, "用户取消"
                dst = os.path.join(images_dir, os.path.basename(src))
                if os.path.exists(src):
                    shutil.copy2(src, dst)
                    copied += 1
            except OSError:
                pass  # 单张图片失败不阻断整体导出

    # 5. 生成 HTML
    _report(progress_callback, "生成网页...", 0, 100)
    html_path = _generate_html(enriched, export_folder, images_dir)
    _report(progress_callback, "生成完成", 100, 100)

    return True, export_folder


# ── internal helpers ────────────────────────────────────────────────

def _report(cb, step, cur, total):
    if cb:
        cb(step, str(cur), str(total))


def _enrich_questions(questions):
    """逐题附加 images、tags、category_name。"""

    # 批量查询所有图片和标签（避免逐题查库）
    all_cats = {c["id"]: c["name"] for c in models.get_all_categories()}
    all_tags = models.get_all_tags()

    enriched = []
    for q in questions:
        qid = q["id"]
        # images
        images = models.get_question_images(qid)
        img_list = []
        for img in images:
            fname = os.path.basename(img["image_path"])
            img_list.append({
                "t": img["image_type"],   # question / answer / notes
                "src": "images/" + fname,
            })
        # tags
        tags = models.get_question_tags(qid)
        tag_names = [t["name"] for t in tags]

        enriched.append({
            "question_text": q.get("question_text", ""),
            "answer_text": q.get("answer_text", ""),
            "notes": q.get("notes", ""),
            "wrong_count": q.get("wrong_count", 0),
            "_cat": all_cats.get(q.get("category_id"), ""),
            "_tags": tag_names,
            "_images": img_list,
        })
    return enriched


def _collect_unique_images(enriched_questions):
    """从富化题目中提取所有不重复的图片文件名，映射回绝对路径。"""
    from config import IMAGE_DIR
    fnames = set()
    for q in enriched_questions:
        for img in q["_images"]:
            fnames.add(os.path.basename(img["src"]))  # e.g. "uuid.jpg"
    return {os.path.join(IMAGE_DIR, f) for f in fnames}


def _create_export_structure(parent_dir):
    """创建导出文件夹和 images 子目录"""
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    export_folder = os.path.join(parent_dir, f"ExportedQB_{ts}")
    images_dir = os.path.join(export_folder, "images")
    os.makedirs(images_dir, exist_ok=True)
    return export_folder, images_dir


def _generate_html(enriched, export_folder, images_dir):
    """生成 index.html"""
    # 图片路径从 images/ 改为相对导出文件夹的路径
    # 已经是 "images/filename" 格式，无需修改

    data_json = json.dumps(enriched, ensure_ascii=False)
    # 防止用户输入的 </script> 破坏 HTML 结构
    data_json = data_json.replace("</script>", r"<\/script>")
    # 验证替换确实发生
    if "{QUESTION_DATA}" in EXPORT_HTML:
        html = EXPORT_HTML.replace("{QUESTION_DATA}", data_json)
    else:
        # 模板可能已有默认空数组，直接替换整行
        html = EXPORT_HTML.replace('var ALL_DATA = []', f'var ALL_DATA = {data_json}')

    html_path = os.path.join(export_folder, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path

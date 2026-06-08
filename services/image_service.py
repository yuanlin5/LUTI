"""
=============================================================================
 图片存取服务
=============================================================================
 负责题目图片的保存和删除。图片文件存储在 data/images/ 目录，
 文件名使用 UUID 随机生成，避免重名冲突。
=============================================================================
"""

import os
import shutil
import uuid
from config import IMAGE_DIR

# 允许上传的图片格式
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}


def save_image(source_path, image_type, quality=20):
    """
    将用户选择的图片复制到 data/images/ 目录。
    source_path — 用户选择的原始文件路径
    image_type — 图片用途：'question'/'answer'/'notes'
    quality    — 压缩比例 (20/50/100)，默认 20%
    返回 (目标路径, None) 成功 或 (None, 错误信息) 失败
    """
    ext = os.path.splitext(source_path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return None, f"不支持的图片格式: {ext}"

    filename = f"{uuid.uuid4().hex}{ext}"
    dest_path = os.path.join(IMAGE_DIR, filename)

    if quality >= 100:
        shutil.copy2(source_path, dest_path)
    else:
        from PyQt5.QtGui import QPixmap
        pixmap = QPixmap(source_path)
        if pixmap.isNull():
            shutil.copy2(source_path, dest_path)
        else:
            w = int(pixmap.width() * quality / 100)
            scaled = pixmap.scaledToWidth(max(1, w))
            scaled.save(dest_path)
    return dest_path, None


def delete_image(image_path):
    """从磁盘删除指定的图片文件"""
    if image_path and os.path.exists(image_path):
        os.remove(image_path)

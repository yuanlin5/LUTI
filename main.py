"""
=============================================================================
 程序入口 —— 双击此文件或通过启动器运行
=============================================================================
 这是软件的启动入口，负责：
   1. 初始化数据库（如果不存在则自动创建）
   2. 创建 Qt 应用程序
   3. 显示主窗口
=============================================================================
"""

import sys
import os

# 确保工作目录是 main.py 所在的文件夹（防止双击运行时找不到依赖文件）
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from database.db_manager import init_db   # 数据库建表
from ui.main_window import MainWindow     # 主窗口


def main():
    """软件启动主流程"""
    # 1. 初始化数据库（自动创建表和必要的文件夹）
    init_db()

    # 2. 创建 Qt 应用程序实例
    app = QApplication(sys.argv)
    app.setApplicationName("我的题库")

    # 3. 创建并显示主窗口
    window = MainWindow()
    window.show()

    # 4. 进入事件循环，等待用户操作
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

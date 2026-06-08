# 技术规范

## 技术栈

| 层面 | 技术 | 说明 |
|------|------|------|
| 编程语言 | Python 3.9+ | 主流版本，库生态丰富 |
| GUI 框架 | PyQt5 5.15+ | Qt5 的 Python 绑定 |
| 数据库 | SQLite 3 | Python 内置，零配置 |
| 图片处理 | Pillow 9.0+ | Python 图像库 |
| 语音识别 | SpeechRecognition 3.10+ | 多引擎语音识别封装 |
| 音频采集 | PyAudio 0.2.12+ | 跨平台音频 I/O |

## 项目结构

```
demo_luti/
├── main.py                 # 程序入口
├── requirements.txt        # Python 依赖
├── config.py               # 全局配置
├── database/
│   ├── __init__.py
│   ├── db_manager.py       # 数据库连接与建表
│   └── models.py           # 数据访问层
├── ui/
│   ├── __init__.py
│   ├── main_window.py      # 主窗口
│   ├── add_question.py     # 录题面板
│   ├── question_list.py    # 题库管理面板
│   ├── exam_panel.py       # 考试面板
│   ├── wrong_collection.py # 错题集面板
│   └── styles.qss          # 全局样式
├── services/
│   ├── __init__.py
│   ├── speech_service.py   # 语音服务
│   ├── exam_service.py     # 组卷逻辑
│   └── image_service.py    # 图片管理
├── data/
│   └── images/             # 图片存储目录
├── docs/                   # 项目文档
├── devlog/                 # 开发日志
└── resources/              # 静态资源
```

## 数据库设计

共 6 张表：categories, tags, questions, question_images, question_tags, exams, exam_answers

详见 `database/db_manager.py` 中的建表语句。

## 命名规范

- 文件名：snake_case（如 `add_question.py`）
- 函数名：snake_case（如 `get_all_categories`）
- 类名：PascalCase（如 `AddQuestionPanel`）
- 常量：UPPER_SNAKE_CASE（如 `PRIMARY_COLOR`）
- 数据库表名：复数 snake_case（如 `question_tags`）
- 数据库字段名：snake_case（如 `question_id`）

## 编码规范

- 文件编码：UTF-8
- 所有面向用户的字符串使用中文
- 代码注释使用中文
- 每个模块只负责一个关注点

# CLAUDE.md - 题库桌面软件项目指引

## 项目简介
一个 Windows 桌面题库管理软件，基于 Python + PyQt5 + SQLite 开发。帮助用户录入错题、管理题库、自动组卷考试、收集错题。

## 标准文件路径

| 文件 | 路径 | 说明 |
|------|------|------|
| 需求文档 | `docs/requirements.md` | 功能需求详细说明 |
| 技术规范 | `docs/tech-spec.md` | 技术栈、项目结构、命名规范 |
| 设计规范 | `docs/design-spec.md` | 配色、布局、字体、交互规范 |
| 执行步骤 | `docs/implementation-plan.md` | 开发步骤和当前进度 |
| 开发日志 | `devlog/YYYY-MM-DD.md` | 每日开发记录 |
| 配置文件 | `config.py` | 全局配置常量 |
| 图标配置 | `resources/icon_config.json` | 软件图标配置文件 |
| 图标文件夹 | `resources/icons/` | 图标图片存放目录 |
| 入口文件 | `main.py` | 程序启动入口 |

## 工作说明

### 开发节奏
1. **每次只推进一个步骤**，确认当前步骤稳定后再进行下一步
2. 每完成一个功能模块，更新 `docs/implementation-plan.md` 中的清单
3. 每次开发结束后，更新当日 `devlog/YYYY-MM-DD.md`（如跨天则新建文件）
4. 开发日志包含：完成事项、待办事项、遇到的问题、下一步计划

### 代码规范
- 遵循 `docs/tech-spec.md` 中的命名和编码规范
- UI 开发遵循 `docs/design-spec.md` 中的设计规范
- 所有功能实现参考 `docs/requirements.md` 确保不遗漏

### 新增功能流程
1. 阅读 `docs/requirements.md` 确认需求
2. 阅读 `docs/tech-spec.md` 和 `docs/design-spec.md` 确认规范
3. 更新 `docs/implementation-plan.md` 添加新步骤
4. 实现功能
5. 更新开发日志

### 自定义图标
1. 将图标图片（PNG 格式推荐）放入 `resources/icons/` 文件夹
2. 编辑 `resources/icon_config.json`，将图标名称对应的文件名填好
3. 例如：`"app_icon": "my_icon.png"` 表示使用 `resources/icons/my_icon.png` 作为应用图标
4. 留空表示不使用自定义图标，软件将使用默认文字

### 启动项目
```bash
pip install -r requirements.txt
python main.py
```

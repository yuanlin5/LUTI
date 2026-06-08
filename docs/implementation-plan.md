# 执行步骤

## 开发原则
- 每个步骤完成后确认功能正常再进入下一步
- 每步只改 2-3 个文件，控制影响范围
- 发现问题立即修复后再继续

## 步骤清单

### 步骤 1：项目结构与依赖 ✓
- [x] 清理旧 C 文件
- [x] 创建目录结构
- [x] 编写 requirements.txt
- [x] 编写 config.py

### 步骤 2：数据库层 ✓
- [x] 创建 db_manager.py（建表）
- [x] 创建 models.py（CRUD 接口）

### 步骤 3：主窗口框架
- [ ] 创建 main_window.py（侧边栏 + 内容区）
- [ ] 创建 styles.qss（全局样式）
- [ ] 创建 main.py（入口文件）

### 步骤 4：录题面板
- [ ] 创建 add_question.py
- [ ] 创建 services/image_service.py

### 步骤 5：题库管理面板
- [ ] 创建 question_list.py

### 步骤 6：考试面板
- [ ] 创建 exam_panel.py
- [ ] 创建 services/exam_service.py

### 步骤 7：错题集面板
- [ ] 创建 wrong_collection.py

### 步骤 8：语音转文字
- [ ] 创建 services/speech_service.py
- [ ] 集成到录题面板

### 步骤 9：美化与测试
- [ ] 统一样式细节
- [ ] 端到端功能测试

## 当前状态
- 已完成：步骤 1、2
- 进行中：步骤 3
- 待完成：步骤 4-9

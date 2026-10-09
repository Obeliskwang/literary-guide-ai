# 伴读精灵 - 经典文学名著导赏系统

> **FastAPI 服务层已接入。** 当前入口为独立 API + Streamlit API 客户端。
> 在本目录分别执行 `python run_local.py api` 和 `python run_local.py ui`。
> Swagger：`http://localhost:8000/docs`；界面：`http://localhost:8501`。
> 详细启动、迁移与验收步骤见 [P0 交付与验收说明](../文档/P0_FastAPI服务层_交付与验收说明.md)。
> 本机旧数据已备份迁移至 demo；不要同时运行旧 `auth_api.py`。

> 基于大模型的经典文学名著阅读导赏与人物关系问答系统

## 项目简介

伴读精灵是一款面向大学生的名著辅助阅读工具，基于 RAG（检索增强生成）技术，让用户提问后获得有原著原文依据的回答。系统涵盖**智能问答、人物关系、练习题**三大功能模块，为经典文学阅读提供全方位辅助。

## 核心功能

### 🤖 智能问答

- **文档上传**：支持 TXT 格式上传，自动识别编码（UTF-8/GBK/GB2312）
- **向量检索**：按行分块 + 向量化存储，自动识别章节标题
- **溯源回答**：基于原文片段生成回答，强制引用出处，标注章节
- **双栏对照**：左侧 AI 回答，右侧原文依据 + 相似度
- **智能拒答**：检索无关时明确拒答，避免幻觉；相关度低时提示用户
- **多轮对话**：保留最近 3 轮上下文，支持追问

### 👥 人物关系

- **人物卡片**：展示人物身份、家族、简介，支持按家族筛选
- **关系图谱**：Mermaid 可视化关系网络（取经团队 / 孙悟空关系网 / 天庭人物）
- **核心事件**：列出重要情节及涉及人物

### 📝 练习题

- **做题模式**：选择题作答，即时提交批改
- **结果统计**：正确率、错题分析、详细解析

### � 多书籍管理

- **书籍管理**：增删改查多本独立书籍知识库
- **向量库隔离**：每本书独立向量库，互不影响
- **统计信息**：显示文件数、分块数

## 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端 | Streamlit | 交互界面 |
| 图表 | Mermaid.js | 人物关系图 |
| RAG | LangChain + ChromaDB | 文档检索与向量存储 |
| 模型 | Qwen2.5 / GPT | 支持 Ollama 本地 / OpenAI API 双模式 |
| 向量 | BGE-M3 | 中文向量化（Ollama 模式） |

## 安装教程

### 1. 安装依赖

```bash
pip install -r libs.txt
```

### 2. 配置文件

```bash
copy config.py.template config.py
```

### 3. 下载模型（Ollama 模式）

```bash
ollama pull qwen2.5:0.5b-instruct
ollama pull bge-m3
```

> 如需使用兼容 Chat Completions 的 AI 模型服务，在现有 `config.py` 中设置 `LLM_TYPE="api"`，并填写 `AI_MODEL_NAME`、`AI_BASE_URL`、`AI_API_KEY`。模型名称填写服务商提供的模型 ID；基础网址不含 `/chat/completions`。修改后重启应用。本地向量模型继续保持 `EMBED_TYPE="ollama"`。

## 使用说明

### 启动应用

已增加本地演示鉴权，启动后在 [http://localhost:8501](http://localhost:8501) 点击登录。测试账号为 `demo / Demo@123456`、`admin / Admin@123456`。鉴权 HTTP 服务随 Streamlit 自动启动于 8000 端口。接口、初始化 SQL、模型 Key 生命周期见 [AUTH_GUIDE.md](AUTH_GUIDE.md)。

```bash
streamlit run app.py
```

### 智能问答

上传时使用本地 Ollama `bge-m3` 切分后向量化并写入 Chroma；提问时仅向量化当前问题并检索已有文档。

侧边栏“回答模型”可选择本地 Ollama 或远程 API。本地填写模型 ID 与 Ollama 地址；远程默认使用项目固定 AI 配置，用户可输入自己的模型 ID、基础网址和 AI API 密钥并保存。本次登录的用户密钥使用 Windows DPAPI 加密，刷新或服务重启后仍有效，退出后清除；留空保存恢复项目默认配置。更换回答模型不会重建向量库。上传和检索始终需要本地 Ollama 及 `bge-m3`，远程回答不要求安装本地聊天模型。

1. 点击「书籍管理」创建/选择书籍
2. 上传 TXT 文本文件
3. 输入问题，获取带原文依据的回答

### 人物关系

选择页面切换到「人物关系」，查看人物卡片、关系图、核心事件表。

### 练习题

选择页面切换到「练习题」，做题并提交，查看结果和错题分析。

## 内置数据

| 书籍 | 人物 | 练习题 |
|------|------|--------|
| 《西游记》 | ✅ 20+ 人物，含关系图谱 | ✅ 章回选择题库 |
| 《红楼梦》 | ✅ 人物关系 | ✅ 练习题 |

数据位于 `data/` 目录，可自行扩展。

## 项目结构

```
literary-ai-guide-master/
├── app.py                  # 主页面
├── book_manager.py         # 书籍管理
├── character_service.py    # 人物关系服务
├── exercise_service.py     # 练习题服务
├── agent.py                # 问答编排
├── rag.py                  # RAG 检索与向量存储
├── llm.py                  # 大模型加载
├── tools.py                # 工具函数
├── utils.py                # 通用工具
├── cli.py                  # 命令行工具
├── config.py.template      # 配置模板
├── libs.txt                # 核心依赖
├── data/                   # 数据目录
│   ├── books.json
│   ├── characters_西游记.json
│   ├── characters_红楼梦.json
│   ├── exercises_西游记.json
│   └── exercises_红楼梦.json
└── tests/                  # 测试用例
```

## 配置说明

主要配置项位于 `config.py`：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| LLM_TYPE | ollama | 大模型类型：ollama / api（兼容原 openai） |
| EMBED_TYPE | ollama | Embedding 类型 |
| OLLAMA_LLM_MODEL | qwen2.5:0.5b-instruct | Ollama 大模型 |
| OLLAMA_EMBED_MODEL | bge-m3 | 向量化模型 |
| CHUNK_LINES | 10 | 按行分块的行数 |
| RETRIEVE_TOP_K | 3 | 召回段落数 |
| SIMILARITY_THRESHOLD | 1.0 | 软拒绝阈值 |
| SOFT_REJECTION_THRESHOLD | 2.0 | 硬拒绝阈值 |
| MAX_CONVERSATION_TURNS | 3 | 对话轮数 |

## CLI 工具

```bash
# 纯聊天
python cli.py

# 带 RAG
python cli.py path/to/book.txt
```

## 测试

```bash
pytest tests/
```

## 许可证

MIT License

## 致谢

- [Streamlit](https://streamlit.io/) · [LangChain](https://www.langchain.com/) · [Chroma](https://www.trychroma.com/) · [Ollama](https://ollama.com/) · [Mermaid](https://mermaid.js.org/)
# SQLite 会话管理

删除书籍会同时删除关联会话及全部历史记录，不会留存；两处确认界面均明确提示。对应旧 JSON 历史也会清理。

智能问答侧边栏支持新建、切换、重命名、删除会话和清空当前会话历史。每个会话关联 `book_id`，同书可建立多个会话；重启后恢复最近书籍、会话及问答来源。会话名为 1–100 字符，删除前需勾选确认。

使用 Python 内置 `sqlite3`，无需新增依赖。记录保存于项目 `data/sessions.sqlite3`，备份时请保存该文件。旧 `chat_history_cache.json` 会自动导入能唯一匹配书名的历史，原文件保留；无法匹配的记录在侧边栏提示。

方案及验收见 [SESSION_PLAN.md](SESSION_PLAN.md)。运行回归：`python -m unittest discover -s tests -p "test_session*.py" -v`。


### 基础习题自测

进入“习题自测”，多选章节和可选难度，点击“开始自测”。全部选择答案后统一提交，显示正误、正确答案、解析和原著章节出处；答题阶段 API 不返回答案。JSON 缺失或无效时提示“习题数据未就绪”，漏答时提示“请先选择答案”。

后端将题目快照和提交结果存入 service.sqlite3 的 exercise_attempts 表，按登录用户与书籍隔离。提交后不可改答案；相同提交重试不增加历史。开始新自测产生新记录，未提交记录不计入统计。题库后续调整不会改变已开始自测或历史判题结果。

“历史记录与分析”提供分页记录、章节统计表、ECharts 章节正确率柱状图和历次正确率折线图。累计正确率 = 所有提交记录的正确次数 / 作答次数；重复练习计入统计。ECharts 5.6.0 从 jsDelivr CDN 加载，浏览器需要联网；加载失败仍可查看统计表。出处 source 字段为原著章节定位，不冒充逐字原文。

新增接口（均需登录）：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /api/books/{book_id}/exercise-attempts | chapters 数组、可选 difficulty；需 Idempotency-Key |
| POST | /api/books/{book_id}/exercise-attempts/{attempt_id}/submit | answers：题目 ID 到选项索引（从 0 开始） |
| GET | /api/books/{book_id}/exercise-attempts | 已提交历史，page/page_size 分页 |
| GET | /api/books/{book_id}/exercise-statistics | 用户当前书籍的累计、章节与趋势统计 |

回归：`python run_local.py test tests/test_exercise_selftest.py tests/test_fastapi_service.py tests/test_api_frontend.py -q`。更新后重启 API 与 Streamlit，数据库表自动创建。

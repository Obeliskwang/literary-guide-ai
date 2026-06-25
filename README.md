# 伴读精灵 - 经典文学名著导赏系统

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

> 如需使用 OpenAI API，设置 `LLM_TYPE="openai"` 并配置 API Key。

## 使用说明

### 启动应用

```bash
streamlit run app.py
```

### 智能问答

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
| LLM_TYPE | ollama | 大模型类型：ollama / openai |
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

# ollama-llm-streamlit-agent

A **local-only** **LLM** assistant that runs on your machine: **Ollama** for models, **LangChain / LangGraph** for a tool-calling agent, optional **RAG** over plain text, and a **Streamlit** UI plus a **terminal CLI**. No cloud LLM API keys are required.

---

## Features

- **Chat agent** with tools: calculator, document search (when RAG is loaded), and **vision** (describe an image from a path on disk).
- **RAG**: chunk text, embed with Ollama, store in an **in-memory Chroma** index, retrieve top‑k chunks for `search_documents`.
- **Two interfaces**: browser (`streamlit run`) and shell (`python cli.py`).
- **Conversation memory** per session thread via LangGraph’s `MemorySaver` checkpointer.
- **Structured logging** to stderr (timestamps, tool calls, timings).

---

## Architecture (short)

| Piece | Role |
|--------|------|
| `config.py` | Model names, chunk sizes, logging setup |
| `llm.py` | `ChatOllama` (chat + vision), `OllamaEmbeddings` |
| `rag.py` | Split text → `Chroma.from_documents` (in-memory) |
| `tools.py` | `@tool` functions; `analyze_image` sends **real image bytes** via LangChain multimodal messages |
| `agent.py` | `langchain.agents.create_agent` → compiled LangGraph with tools + checkpointer |
| `app.py` | Streamlit: upload text, chat, stable RAG re-indexing via content hash |
| `cli.py` | Optional file path → index → same agent as the UI |
| `ollama_check.py` | Verifies required Ollama models exist locally before the UI or CLI starts |

---

## Prerequisites

- **Python** 3.11+ (tested with **3.12.3**)
- **[Ollama](https://ollama.com/)** installed and running (`ollama serve` or the desktop app)

---

## Get the code

Example clone location:

```bash
git clone https://github.com/amirsaleem1990/ollama-llm-streamlit-agent
cd ollama-llm-streamlit-agent
```

Use any directory you prefer; adjust paths below accordingly.

---

## Download Ollama models (required)

The app expects **chat**, **embedding**, and **vision** models whose names match **`config.py`** (`LLM_MODEL`, `EMBED_MODEL`, `VISION_MODEL`). **Pull them before running** the UI or CLI:

```bash
ollama pull llama3.2
ollama pull mxbai-embed-large
ollama pull llava
ollama list
```

Confirm tags such as `llama3.2:latest` appear. If anything is missing, **`app.py` shows an error in the browser** and **`cli.py` exits with code 2**, with instructions listing the exact `ollama pull …` commands.

To use different model names, edit `config.py` and pull those tags instead.

---

## Installation (Python dependencies)

```bash
cd ollama-llm-streamlit-agent
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -U pip
pip install streamlit langchain langchain_community langchain-ollama langchain-text-splitters python-dotenv
```

The [`libs`](libs) file lists the direct dependencies; `langchain` pulls **langgraph** and related packages transitively.

Optional: copy [`.env.example`](.env.example) to `.env` and edit values. Variables are loaded when `config` is imported (requires `python-dotenv`).

---

## Tests

Install dev dependencies and run **pytest** from the project root (tests mock Ollama / Chroma so a running server is **not** required):

```bash
pip install -r requirements-dev.txt
pytest
```

For verbose output: `pytest -v`.

`tests/conftest.py` sets **`SKIP_OLLAMA_CHECK=1`** so the suite does not require models to be installed; the runtime UI/CLI still enforce the check unless you set that variable yourself.

---

## Configuration

Edit **`config.py`**:

| Variable | Purpose | Default |
|----------|---------|---------|
| `LLM_MODEL` | Main chat model | `llama3.2` |
| `EMBED_MODEL` | Embeddings for RAG | `mxbai-embed-large` |
| `VISION_MODEL` | Image description | `llava` |
| `TEMPERATURE` | Chat sampling | `0.6` |
| `CHUNK_SIZE` | RAG chunk length | `500` |
| `CHUNK_OVERLAP` | RAG overlap | `50` |

---

## Environment variables

| Variable | Effect |
|----------|--------|
| `LOG_LEVEL` | Python logging level (`INFO`, `DEBUG`, …). Default: `INFO`. |
| `AGENT_GRAPH_DEBUG` | If `1` / `true` / `yes`, enables verbose LangGraph execution logging. |
| `OLLAMA_HOST` | Base URL for the Ollama API (default `http://127.0.0.1:11434`). Used when checking `/api/tags` and by LangChain’s Ollama clients. |
| `SKIP_OLLAMA_CHECK` | If `1` / `true` / `yes`, skips the **local model** check at startup (useful for tests or special setups). **Do not use in production** unless you know Ollama models are guaranteed available. |

### `.env` file

See **[`.env.example`](.env.example)** for documented keys and defaults.

```bash
cp .env.example .env
# edit .env, then run the app as usual
```

`config.py` loads `.env` from the project root when **`python-dotenv`** is installed. You can still override values in the shell for a single run:

```bash
LOG_LEVEL=DEBUG AGENT_GRAPH_DEBUG=1 .venv/bin/streamlit run app.py
```

---

## Web UI

```bash
cd ollama-llm-streamlit-agent
.venv/bin/streamlit run app.py
```

Open the URL shown (usually **http://localhost:8501**).

1. Optionally upload a **plain-text** file (UTF‑8). The app hashes bytes and only re-embeds when the file **changes** (avoids empty reads on Streamlit reruns).
2. Chat in the input box. Logs appear in the **terminal** where Streamlit runs.

---

## CLI

```bash
# Chat only (calculator + vision tools; no RAG)
.venv/bin/python cli.py

# Index a text file and enable RAG (search_documents)
.venv/bin/python cli.py /path/to/notes.txt

# Non‑UTF‑8 encodings
.venv/bin/python cli.py ./legacy.txt --encoding latin-1
```

Same agent graph as the UI; CLI uses thread id `cli_session`. Assistant output goes to **stdout**; logs to **stderr**.

---

## Tools (behavior)

### `calculator`

Evaluates a string as a Python expression (`eval`). **Dangerous in untrusted settings**—only run the app in environments you trust.

### `search_documents`

Present only when a vector store exists. Runs **similarity search** (`k=3` in `retrieve`) and returns concatenated chunk text. **Re-indexing replaces** the previous corpus; there is **no append** of multiple files into one growing index in the current design.

### `analyze_image`

- Accepts a **local path**; expands `~` and env vars such as `$HOME`.
- Reads the file and sends the image to the vision model using LangChain’s **`HumanMessage` + `image_url` (data URL + base64)** so Ollama receives real pixels (not text-only prompts).

---

## RAG details

- **Input**: raw string from the UI (UTF‑8 decode) or CLI (`read_text` with `--encoding`).
- **Splitting**: `RecursiveCharacterTextSplitter` with `CHUNK_SIZE` / `CHUNK_OVERLAP`.
- **Store**: **Chroma in memory**—restarting the process **drops** the index unless you re-upload / re-pass the file.
- **UI nuance**: `st.file_uploader` is handled with `seek(0)` and **content-hash** so reruns don’t wipe the corpus with an empty read.

---

## Logging

- Default format: `timestamp | LEVEL | logger | message` on **stderr**.
- HTTP libraries (`httpx`, `httpcore`, `urllib3`) are capped at **WARNING** to reduce noise.

---

## Security and limitations

- **`calculator`** uses **`eval`**—do not expose this app to untrusted users or the public internet without replacing it with a safe math evaluator.
- **Vision** and **RAG** read **local files** you or the model reference; paths are resolved on the machine running Ollama.
- **No authentication** is implemented.
- Supported uploads for RAG are effectively **plain text** (UI: UTF‑8). PDF/Word are not parsed.

---

## Troubleshooting

| Issue | Things to check |
|--------|------------------|
| Connection errors to Ollama | `ollama list`, `curl http://127.0.0.1:11434/api/tags` |
| “Required Ollama models are missing” | Run the `ollama pull …` lines from the error (or README), then `ollama list` |
| RAG seems empty in the UI after upload | Ensure you’re on a version with **seek + hash**; watch logs for chunk counts |
| Vision describes the wrong thing | Older code paths could send **no image bytes**; current code uses base64 `image_url`. Confirm logs show image **byte size** |
| CLI vs UI answers differ | Different **thread ids** and history; compare with a **fresh** browser session and the same question |
| Slow first RAG index | Embedding **every chunk** hits Ollama; large files take time |

---

## Project layout

```
ollama-llm-streamlit-agent/
├── README.md
├── .env.example         # template for environment variables (copy to `.env`)
├── .gitignore           # ignores `.env`, `.venv`, etc.
├── pytest.ini           # pytest config (pythonpath = project root)
├── requirements-dev.txt # pytest (dev / CI)
├── libs                 # pip package list (informal)
├── tests/               # unit tests (mocked LLM / vector store)
├── ollama_check.py      # verify Ollama models exist before startup
├── config.py            # models, chunks, logging
├── llm.py               # Ollama chat / embeddings / vision
├── rag.py               # Chroma + split + retrieve
├── tools.py             # tool definitions
├── agent.py             # create_agent graph
├── app.py               # Streamlit UI
└── cli.py               # terminal entrypoint
```

---

## License

Add a `LICENSE` file of your choice (e.g. MIT) when you publish the repository.

---

## Acknowledgements

Built with [Ollama](https://ollama.com/), [LangChain](https://github.com/langchain-ai/langchain), [Streamlit](https://streamlit.io/), and [Chroma](https://www.trychroma.com/) (via LangChain).

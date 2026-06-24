import logging
import traceback
from rag import retrieve
import requests
from openai import OpenAI

from config import (
    MAX_CONVERSATION_TURNS,
    MAX_PROMPT_CHARS,
    LLM_TYPE,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    REJECTION_MESSAGE,
    TEMPERATURE,
    LLM_MODEL,
    )

logger = logging.getLogger(__name__)


def check_model_health():
    """检查模型服务是否可用"""
    if LLM_TYPE == "openai":
        try:
            client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
            client.models.list()
            return True
        except Exception as e:
            logger.warning("OpenAI API health check failed: %s", e)
            return False
    else:
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.warning("Ollama health check failed: %s", e)
            return False


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n\n[内容过长，已截断]"


def _format_history_for_prompt(history):
    """Format prior turns for inclusion in the prompt."""
    if not history:
        return ""

    lines = []
    for turn in history[-MAX_CONVERSATION_TURNS:]:
        question = str(turn.get("question", "")).strip()
        answer = str(turn.get("answer", "")).strip()
        if not question and not answer:
            continue
        if len(answer) > 240:
            answer = answer[:240] + "..."
        lines.append(f"用户：{question}")
        lines.append(f"助手：{answer}")
        lines.append("")
    return "\n".join(lines).strip()


def build_rag_prompt(retrieved_chunks, question, history=None):
    """Build a source-grounded prompt with bounded context."""
    chunks = []
    history_context = _format_history_for_prompt(history)

    chunk_budget = MAX_PROMPT_CHARS - len(history_context) - len(question) - 700
    chunk_budget = max(1200, min(chunk_budget, MAX_PROMPT_CHARS - 500))

    remaining = chunk_budget
    for i, chunk in enumerate(retrieved_chunks):
        text = chunk["document"].page_content.strip()
        if not text:
            continue
        text = _truncate_text(text, min(len(text), 1200))
        block = f"【片段 {i + 1}】\n{text}"
        if len(block) > remaining:
            if remaining <= 0:
                break
            block = block[:remaining]
        chunks.append(block)
        remaining -= len(block)

    chunks_text = "\n\n".join(chunks)
    if history_context:
        prompt = f"""你是一个经典文学导读助手。下面给你最近的对话历史、检索到的原著片段和当前问题。请优先基于原著片段作答，并尽量把多个相关片段拼接成完整回答。

对话历史：
{history_context}

规则：
1. 只能使用提供的原著片段中的信息，不要引入外部知识。
2. 回答时尽量综合多个片段，形成连贯答案。
3. 必须标注引用的原文出处。
4. 如果片段确实不足以支撑回答，请简要说明证据不足，不要编造。

原著片段：
{chunks_text}

当前问题：{question}
"""
    else:
        prompt = f"""你是一个经典文学导读助手。请严格基于下面的原著片段回答当前问题，并尽量把相关片段拼接成完整答案。

规则：
1. 只能使用提供的原著片段中的信息，不要引入外部知识。
2. 回答时可以综合多个片段，不要只机械复述单段。
3. 必须标注引用的原文出处。
4. 如果片段确实不足以支撑回答，请简要说明证据不足，不要编造。

原著片段：
{chunks_text}

当前问题：{question}
"""
    return _truncate_text(prompt, MAX_PROMPT_CHARS)


def generate_answer(vectordb, query, retrieved_results=None, conversation_history=None):
    """Generate answer with cited source snippets."""

    if retrieved_results is None:
        retrieved_results = retrieve(vectordb, query)

    if retrieved_results.get("reject"):
        logger.info("generate_answer: rejecting query %r", query)
        return {
            "answer": REJECTION_MESSAGE,
            "sources": [],
            "rejected": True,
            "soft_reject": False,
        }

    logger.info("generate_answer: generating answer for query %r", query)

    if not check_model_health():
        logger.error("generate_answer: Model service is not responding")
        service_name = "OpenAI API" if LLM_TYPE == "openai" else "Ollama"
        return {
            "answer": f"{service_name}服务暂时不可用，请检查服务是否正常运行",
            "sources": [],
            "rejected": False,
            "error": f"{service_name} service unavailable",
        }

    prompt = build_rag_prompt(retrieved_results["results"], query, conversation_history)

    try:
        logger.info("generate_answer: invoking model %s (type: %s)", LLM_MODEL, LLM_TYPE)

        answer = ""
        if LLM_TYPE == "openai":
            client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
            messages = [
                {
                    "role": "system",
                    "content": "你是一个专业的文学名著导读助手，擅长从原著文本中提取准确的信息并给出有依据的回答。",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
            response = client.chat.completions.create(
                model=LLM_MODEL,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=256,
                stream=False,
            )
            answer = response.choices[0].message.content
        else:
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的文学名著导读助手，擅长从原著文本中提取准确的信息并给出有依据的回答。",
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "stream": False,
                "options": {
                    "temperature": TEMPERATURE,
                    "num_predict": 256,
                },
            }
            response = requests.post(
                "http://localhost:11434/api/chat",
                json=payload,
                timeout=60,
            )
            if response.status_code != 200:
                raise RuntimeError(
                    f"Ollama chat API error: {response.status_code} {response.text[:1000]}"
                )
            data = response.json()
            message = data.get("message") or {}
            answer = message.get("content", "")

        if not answer:
            raise RuntimeError(f"API returned empty message")

        logger.info("generate_answer: model responded successfully")

        if retrieved_results.get("soft_reject"):
            answer = f"{retrieved_results.get('soft_message', '')}\n\n{answer}"

        sources = []
        for chunk in retrieved_results["results"]:
            sources.append(
                {
                    "text": chunk["document"].page_content,
                    "distance": chunk["distance"],
                    "metadata": chunk["document"].metadata,
                }
            )

        return {
            "answer": answer,
            "sources": sources,
            "rejected": False,
            "soft_reject": retrieved_results.get("soft_reject", False),
            "min_distance": retrieved_results["min_distance"],
        }
    except Exception as e:
        logger.error("generate_answer failed: %s", e)
        logger.debug("generate_answer traceback:\n%s", traceback.format_exc())
        return {
            "answer": "生成回答时发生错误，请重试",
            "sources": [],
            "rejected": False,
            "error": str(e),
        }

import base64
import logging
import mimetypes
import os
from pathlib import Path

from langchain.tools import tool
# from langchain_core.messages import HumanMessage  # 暂时注释掉，vision 功能不需要

# from llm import get_vision_llm  # 暂时注释掉，项目暂时不需要 llava 模型
from rag import retrieve

logger = logging.getLogger(__name__)


# 暂时注释掉 vision 相关的辅助函数
# def _resolve_local_path(path: str) -> str:
#     """Expand ~, $HOME-style vars, then absolute path for Ollama / OS."""
#     expanded = os.path.expandvars(os.path.expanduser(path.strip()))
#     return str(Path(expanded).resolve())


# def _human_message_with_image(prompt: str, image_path: str) -> HumanMessage:
#     """Build multimodal input ChatOllama actually forwards to Ollama (see langchain_ollama chat_models)."""
#     path = Path(image_path)
#     data = path.read_bytes()
#     mime, _ = mimetypes.guess_type(str(path))
#     if not mime:
#         mime = "image/png"
#     b64 = base64.b64encode(data).decode("ascii")
#     data_url = f"data:{mime};base64,{b64}"
#     return HumanMessage(
#         content=[
#             {"type": "text", "text": prompt},
#             {"type": "image_url", "image_url": data_url},
#         ]
#     )


@tool
def calculator(expression: str) -> str:
    """Evaluate simple python math expressions"""
    logger.info("Tool calculator: expression=%r", expression)
    try:
        out = str(eval(expression))
        logger.info("Tool calculator: ok result_len=%s", len(out))
        return out
    except Exception as e:
        logger.warning("Tool calculator: error %s", e)
        return str(e)


def build_search_documents_tool(vectordb):
    """Return a tool that searches the given vector store (one tool per loaded corpus)."""

    @tool
    def search_documents(query: str) -> str:
        """Search the loaded documents for passages relevant to the query. Use for questions about document content."""
        logger.info("Tool search_documents: query=%r", query)
        docs = retrieve(vectordb, query)
        text = "\n".join([d.page_content for d in docs])
        logger.info("Tool search_documents: chunks=%s out_chars=%s", len(docs), len(text))
        return text

    return search_documents


# 暂时注释掉 analyze_image 工具，项目暂时不需要 llava 模型
# @tool
# def analyze_image(image_path: str) -> str:
#     """Load an image from a local path and describe it with the vision model. Paths may use ~ and env vars like $HOME."""
#     resolved = _resolve_local_path(image_path)
#     logger.info("Tool analyze_image: raw=%r resolved=%r", image_path, resolved)
#     if not Path(resolved).is_file():
#         msg = f"No file at {resolved!r} (from {image_path!r})"
#         logger.warning(msg)
#         return msg

#     img_bytes = Path(resolved).stat().st_size
#     logger.info(
#         "Tool analyze_image: sending image bytes to vision model (path=%r size=%s)",
#         resolved,
#         img_bytes,
#     )

#     llm = get_vision_llm()
#     msg = _human_message_with_image(
#         "Describe this image in detail.",
#         resolved,
#     )
#     response = llm.invoke([msg])

#     content = response.content
#     clen = len(content) if isinstance(content, str) else len(str(content))
#     logger.info("Tool analyze_image: vision response chars=%s", clen)
#     return content

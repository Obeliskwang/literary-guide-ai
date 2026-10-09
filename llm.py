import os
import requests
from typing import List
from langchain_ollama import ChatOllama
from langchain_core.embeddings import Embeddings
from config import (
    EMBED_MODEL,
    OLLAMA_EMBED_MODEL,
    EMBED_TYPE,
    LLM_MODEL,
    LLM_TYPE,
    AI_API_KEY,
    AI_BASE_URL,
    TEMPERATURE,
)


class OllamaEmbeddings(Embeddings):
    """自定义 Ollama Embedding 类"""

    def __init__(self, model_name: str = "bge-m3", base_url: str = "http://localhost:11434"):
        self.model_name = model_name
        self.base_url = base_url

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """嵌入文档列表"""
        embeddings = []
        for text in texts:
            try:
                response = requests.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": self.model_name, "prompt": text},
                    timeout=120,
                )
                if response.status_code == 200:
                    embedding = response.json()["embedding"]
                    embeddings.append(embedding)
                else:
                    raise Exception(f"Ollama API 错误: {response.status_code}")
            except Exception as e:
                raise Exception(f"获取 embedding 失败: {e}")
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """嵌入单个查询"""
        return self.embed_documents([text])[0]


def get_embeddings():
    """上传文档和检索问题统一使用本地 Ollama 向量模型。"""
    return OllamaEmbeddings(
        model_name=OLLAMA_EMBED_MODEL,
        base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
    )


def get_llm():
    """获取 LLM 实例，根据 LLM_TYPE 选择"""
    temperature = float(os.environ.get("OLLAMA_TEMPERATURE", TEMPERATURE))

    if LLM_TYPE in ("api", "openai"):
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=LLM_MODEL,
            temperature=temperature,
            api_key=AI_API_KEY,
            base_url=AI_BASE_URL,
        )
    else:
        model_name = os.environ.get("OLLAMA_MODEL", LLM_MODEL)
        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        return ChatOllama(
            model=model_name,
            temperature=temperature,
            base_url=base_url,
        )

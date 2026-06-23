import os
import requests
from typing import List
from langchain_ollama import ChatOllama
from langchain_core.embeddings import Embeddings
from config import EMBED_MODEL, LLM_MODEL, TEMPERATURE


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
                    timeout=120
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
    """获取 Ollama embedding 实例"""
    return OllamaEmbeddings(model_name=EMBED_MODEL)

def get_llm():
    # 优先从环境变量读取配置，否则使用 config.py 中的默认值
    model_name = os.environ.get("OLLAMA_MODEL", LLM_MODEL)
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    temperature = float(os.environ.get("OLLAMA_TEMPERATURE", TEMPERATURE))
    
    return ChatOllama(
        model=model_name,
        temperature=temperature,
        base_url=base_url,
        # 可以添加其他参数
        # num_predict=2048,  # 最大生成token数
        # top_k=40,
        # top_p=0.9,
    )
import logging
import os
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from config import REJECTION_MESSAGE, TEMPERATURE

logger = logging.getLogger(__name__)


def build_rag_prompt(retrieved_chunks, question):
    """构建溯源问答Prompt，强制引用原文"""
    chunks_text = "\n\n".join([f"【片段{i+1}】{chunk['document'].page_content}" for i, chunk in enumerate(retrieved_chunks)])
    
    prompt = f"""你是一个经典文学名著伴读助手。请严格基于以下原著片段回答用户问题。

规则：
1. 只能使用提供的原著片段中的信息作答，禁止使用外部知识
2. 回答中必须标注引用的原文出处，格式：→ "引用内容"
3. 如果提供的片段不足以回答问题，请回复：{REJECTION_MESSAGE}
4. 禁止编造任何未在原文中出现的内容
5. 区分回答类型：情节提问需讲清来龙去脉，人物提问需说明身份与关系，细节考据需给出原文依据

原著片段：
{chunks_text}

用户问题：{question}
"""
    return prompt


def generate_answer(vectordb, query, retrieved_results=None):
    """生成带原文引用的回答"""
    from rag import retrieve
    
    if retrieved_results is None:
        retrieved_results = retrieve(vectordb, query)
    
    if retrieved_results.get("reject"):
        logger.info(f"generate_answer: rejecting query '{query}'")
        return {
            "answer": REJECTION_MESSAGE,
            "sources": [],
            "rejected": True
        }
    
    logger.info(f"generate_answer: generating answer for query '{query}'")
    
    prompt = build_rag_prompt(retrieved_results["results"], query)
    
    model = ChatOllama(
        model="llama3.2",
        temperature=TEMPERATURE,
        base_url="http://localhost:11434"
    )
    
    messages = [
        SystemMessage(content="你是一个专业的文学名著解读助手，擅长从原著文本中提取准确信息并给出有依据的回答。"),
        HumanMessage(content=prompt)
    ]
    
    try:
        response = model.invoke(messages)
        answer = response.content
        
        sources = []
        for i, chunk in enumerate(retrieved_results["results"]):
            sources.append({
                "text": chunk["document"].page_content,
                "distance": chunk["distance"],
                "metadata": chunk["document"].metadata
            })
        
        return {
            "answer": answer,
            "sources": sources,
            "rejected": False,
            "min_distance": retrieved_results["min_distance"]
        }
    except Exception as e:
        logger.error(f"generate_answer failed: {e}")
        return {
            "answer": "生成回答时发生错误，请重试",
            "sources": [],
            "rejected": False,
            "error": str(e)
        }

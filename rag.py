import logging
import time
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from chromadb.utils import embedding_functions  # 新增导入
from llm import get_embeddings

from config import CHUNK_OVERLAP, CHUNK_SIZE, EMBED_BATCH_SIZE, EMBED_MAX_RETRIES, SIMILARITY_THRESHOLD, RETRIEVE_TOP_K, REJECTION_MESSAGE

logger = logging.getLogger(__name__)


def create_vector_store(text):
    """
    创建向量存储，使用 Ollama embedding 函数
    """
    # 获取 embeddings（现在返回的是 OllamaEmbeddings 实例）
    embeddings = get_embeddings()

    logger.info(f"create_vector_store: input_chars={len(text)}")
    
    # 分割文本
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(text)
    docs = [Document(page_content=t) for t in chunks]
    logger.info(f"create_vector_store: chunks={len(docs)}")
    
    
    vectordb = None
    total_batches = (len(docs) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE
    
    for batch_idx in range(total_batches):
        start_idx = batch_idx * EMBED_BATCH_SIZE
        end_idx = min(start_idx + EMBED_BATCH_SIZE, len(docs))
        batch_docs = docs[start_idx:end_idx]
        
        logger.info(f"create_vector_store: batch {batch_idx+1}/{total_batches}")
        
        for retry in range(EMBED_MAX_RETRIES):
            try:
                if vectordb is None:
                    # 使用 embed_function 替代 get_embeddings()
                    vectordb = Chroma.from_documents(
                        batch_docs,
                        embedding=embeddings,
                    )
                    logger.info("create_vector_store: initial Chroma index created")
                else:
                    vectordb.add_documents(batch_docs)
                    logger.info(f"create_vector_store: batch {batch_idx+1} added")
                break
            except Exception as e:
                logger.warning(f"batch {batch_idx+1} retry {retry+1} failed: {e}")
                if retry < EMBED_MAX_RETRIES - 1:
                    wait_time = 2 ** retry
                    time.sleep(wait_time)
                else:
                    raise RuntimeError(
                        f"创建向量存储失败（批次 {batch_idx+1}/{total_batches}）：{e}\n"
                        f"建议：减小 EMBED_BATCH_SIZE 或增加 EMBED_TIMEOUT"
                    ) from e
    
    logger.info(f"create_vector_store: Chroma index ready with {len(docs)} chunks")
    return vectordb

def retrieve(vectordb, query):
    logger.info(f"retrieve: query={query}")
    out = vectordb.similarity_search_with_score(query, k=RETRIEVE_TOP_K)
    logger.info(f"retrieve: hits={len(out)}")
    
    results_with_score = []
    min_distance = float('inf')
    
    for doc, distance in out:
        logger.debug(f"retrieve: doc chunk preview='{doc.page_content[:50]}...', distance={distance}")
        results_with_score.append({"document": doc, "distance": distance})
        if distance < min_distance:
            min_distance = distance
    
    logger.info(f"retrieve: min_distance={min_distance}, threshold={SIMILARITY_THRESHOLD}")
    
    if min_distance > SIMILARITY_THRESHOLD:
        logger.info(f"retrieve: no matching results below threshold, rejecting (min_distance={min_distance})")
        return {"reject": True, "message": REJECTION_MESSAGE, "min_distance": min_distance}
    
    return {"reject": False, "results": results_with_score, "min_distance": min_distance}
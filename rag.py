import logging
import re
import time
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from chromadb.utils import embedding_functions  # 新增导入
from llm import get_embeddings

from config import (
    CHUNK_OVERLAP, CHUNK_SIZE,
    EMBED_BATCH_SIZE, EMBED_MAX_RETRIES, SIMILARITY_THRESHOLD, 
    SOFT_REJECTION_THRESHOLD, RETRIEVE_TOP_K, REJECTION_MESSAGE, 
    SOFT_REJECTION_MESSAGE,
    CHUNK_LINES, CHUNK_LINE_OVERLAP
)

logger = logging.getLogger(__name__)


def extract_chapter_metadata(text):
    """
    从文本中提取章节元数据
    支持多种章节格式：第X章、卷X、Part X、Chapter X等
    """
    lines = text.split('\n')
    chapters = []
    current_chapter = None
    chapter_patterns = [
        r'^\s*第[零一二三四五六七八九十百千万\d]+[章回部卷节].*',
        r'^\s*[卷部篇集]第[零一二三四五六七八九十百千万\d]+.*',
        r'^\s*(Chapter|CHAPTER|Part|PART)\s*[IVXLCDM\d]+.*',
        r'^\s*[IVXLCDM\d]+\s*[章回节].*',
        r'^\s*[一二三四五六七八九十\d]+\s*、.*',
    ]
    
    for line_num, line in enumerate(lines, 1):
        for pattern in chapter_patterns:
            if re.match(pattern, line):
                if current_chapter:
                    current_chapter['end_line'] = line_num - 1
                    chapters.append(current_chapter)
                current_chapter = {
                    'title': line.strip(),
                    'start_line': line_num,
                    'end_line': None
                }
                break
    
    if current_chapter:
        current_chapter['end_line'] = len(lines)
        chapters.append(current_chapter)
    
    logger.info(f"extract_chapter_metadata: found {len(chapters)} chapters")
    return chapters


def split_text_by_lines(text, lines_per_chunk=CHUNK_LINES, overlap_lines=CHUNK_LINE_OVERLAP):
    """
    基于行数的文本分块方法
    :param text: 原始文本
    :param lines_per_chunk: 每个chunk的行数
    :param overlap_lines: chunk之间的重叠行数
    :return: 包含元数据的Document列表
    """
    lines = text.split('\n')
    docs = []
    total_lines = len(lines)
    
    # 提取章节信息
    chapters = extract_chapter_metadata(text)
    
    i = 0
    chunk_index = 0
    
    while i < total_lines:
        # 计算当前chunk的范围
        end = min(i + lines_per_chunk, total_lines)
        chunk_lines = lines[i:end]
        
        # 找到当前chunk所属的章节
        current_chapter = None
        for chapter in chapters:
            if chapter['start_line'] <= i + 1 <= chapter['end_line']:
                current_chapter = chapter['title']
                break
        
        # 拼接chunk内容
        chunk_text = '\n'.join(chunk_lines)
        
        # 创建Document并添加元数据
        metadata = {
            'chunk_index': chunk_index,
            'start_line': i + 1,
            'end_line': end,
            'total_lines': total_lines,
            'chapter': current_chapter if current_chapter else '未知章节'
        }
        
        docs.append(Document(page_content=chunk_text, metadata=metadata))
        chunk_index += 1
        
        # 移动到下一个chunk（考虑重叠）
        if i + lines_per_chunk < total_lines:
            i += lines_per_chunk - overlap_lines
        else:
            break
    
    logger.info(f"split_text_by_lines: created {len(docs)} chunks from {total_lines} lines")
    return docs


def create_vector_store(text, mode='new'):
    """
    创建向量存储，使用 Ollama embedding 函数
    
    :param text: 要索引的文本内容
    :param mode: 创建模式 'new'（新建）、'overwrite'（覆盖）、'append'（追加）
    :return: Chroma向量库实例
    """
    # 获取 embeddings（现在返回的是 OllamaEmbeddings 实例）
    embeddings = get_embeddings()

    logger.info(f"create_vector_store: input_chars={len(text)}, mode={mode}")
    
    # 使用基于字符数的分块方法（更稳定，避免Ollama 500错误）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    chunks = splitter.split_text(text)
    
    # 提取章节元数据
    chapters = extract_chapter_metadata(text)
    
    # 为每个chunk添加章节元数据
    docs = []
    lines = text.split('\n')
    current_line = 0
    
    for i, chunk in enumerate(chunks):
        # 找到当前chunk所在的章节
        current_chapter = None
        chunk_lines = chunk.count('\n') + 1
        
        for chapter in chapters:
            if chapter['start_line'] <= current_line + 1 <= chapter['end_line']:
                current_chapter = chapter['title']
                break
        
        metadata = {
            'chunk_index': i,
            'start_line': current_line + 1,
            'end_line': min(current_line + chunk_lines, len(lines)),
            'chapter': current_chapter if current_chapter else '未知章节'
        }
        docs.append(Document(page_content=chunk, metadata=metadata))
        current_line += chunk_lines - CHUNK_OVERLAP // 14  # 估算重叠行数
    
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
                        collection_metadata={"hnsw:space": "cosine"},  # 关键：指定余弦空间
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


def clear_vector_store(vectordb):
    """
    清空向量库中的所有数据
    :param vectordb: Chroma向量库实例
    :return: None
    """
    if vectordb is not None:
        collection = vectordb._client.get_collection(vectordb._collection.name)
        count = collection.count()
        collection.delete(ids=collection.get()['ids'])
        logger.info(f"clear_vector_store: deleted {count} documents")


def get_vector_store_stats(vectordb):
    """
    获取向量库统计信息
    :param vectordb: Chroma向量库实例
    :return: 统计信息字典
    """
    if vectordb is None:
        return {'document_count': 0}
    
    collection = vectordb._client.get_collection(vectordb._collection.name)
    return {
        'document_count': collection.count()
    }

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
    
    logger.info(f"retrieve: min_distance={min_distance}, soft_threshold={SIMILARITY_THRESHOLD}, hard_threshold={SOFT_REJECTION_THRESHOLD}")
    
    # 完全拒答：距离超过硬阈值
    if min_distance > SOFT_REJECTION_THRESHOLD:
        logger.info(f"retrieve: no matching results below hard threshold, rejecting (min_distance={min_distance})")
        return {"reject": True, "message": REJECTION_MESSAGE, "min_distance": min_distance, "soft_reject": False}
    
    # 按距离排序并过滤低相关性结果
    results_with_score.sort(key=lambda x: x["distance"])
    
    # 过滤距离超过硬阈值的结果
    filtered_results = [r for r in results_with_score if r["distance"] <= SOFT_REJECTION_THRESHOLD]
    logger.info(f"retrieve: filtered to {len(filtered_results)} relevant results")
    
    # 软拒答：距离超过软阈值但低于硬阈值
    if min_distance > SIMILARITY_THRESHOLD:
        logger.info(f"retrieve: results below hard threshold but above soft threshold, soft rejecting (min_distance={min_distance})")
        return {"reject": False, "results": filtered_results, "min_distance": min_distance, "soft_reject": True, "soft_message": SOFT_REJECTION_MESSAGE}
    
    # 正常匹配
    return {"reject": False, "results": filtered_results, "min_distance": min_distance, "soft_reject": False}
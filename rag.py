import logging
import re
import shutil
import time
from pathlib import Path

from chromadb.utils import embedding_functions
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import (
    CHUNK_LINE_OVERLAP,
    CHUNK_LINES,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBED_BATCH_SIZE,
    EMBED_MAX_RETRIES,
    MAX_CHUNK_CHARS,
    REJECTION_MESSAGE,
    RETRIEVE_TOP_K,
    SIMILARITY_THRESHOLD,
    SOFT_REJECTION_MESSAGE,
    SOFT_REJECTION_THRESHOLD,
)
from llm import get_embeddings

logger = logging.getLogger(__name__)

PERSIST_DIR = Path("chroma_db")


def clean_text(text):
    """�����ı���ϴ��ͳһ���С�ɾ���հ��С�ѹ�����ڿհס����˹���С�"""
    if not text:
        return text

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    ad_patterns = [
        r"^.{0,5}(���|�ƹ�|����|����|����|��Ƹ|��Ƹ).{0,20}$",
        r"^.{0,10}(http|https|www\.|\.com|\.cn).{0,30}$",
        r"^\s*\[.*?(���|�ƹ�|����).*\]\s*$",
        r"^\s*(��ע|ɨ��|���|΢��|��ϵ��).{0,20}$",
    ]

    cleaned_lines = []
    previous_was_blank = False

    for raw_line in text.split("\n"):
        stripped = raw_line.strip()

        if not stripped:
            if cleaned_lines and not previous_was_blank:
                cleaned_lines.append("")
            previous_was_blank = True
            continue

        previous_was_blank = False

        if any(re.match(pattern, stripped, re.IGNORECASE) for pattern in ad_patterns):
            continue

        cleaned_lines.append(" ".join(stripped.split()))

    result = "\n".join(cleaned_lines).strip()
    logger.info("clean_text: cleaned from %d chars to %d chars", len(text), len(result))
    return result


def extract_chapter_metadata(text):
    lines = text.split("\n")
    chapters = []
    current_chapter = None
    chapter_patterns = [
        r"^\s*第[一二三四五六七八九十百千万\d]+[章节回部卷篇].*",
        r"^\s*[卷部篇集]第[一二三四五六七八九十百千万\d]+.*",
        r"^\s*(Chapter|CHAPTER|Part|PART)\s*[IVXLCDM\d]+.*",
        r"^\s*[IVXLCDM\d]+\s*[章节回篇].*",
        r"^\s*[一二三四五六七八九十\d]+\s*[�]?"
    ]

    for line_num, line in enumerate(lines, 1):
        for pattern in chapter_patterns:
            if re.match(pattern, line):
                if current_chapter:
                    current_chapter["end_line"] = line_num - 1
                    chapters.append(current_chapter)
                current_chapter = {
                    "title": line.strip(),
                    "start_line": line_num,
                    "end_line": None,
                }
                break

    if current_chapter:
        current_chapter["end_line"] = len(lines)
        chapters.append(current_chapter)

    logger.info("extract_chapter_metadata: found %s chapters", len(chapters))
    return chapters


def split_text_by_lines(text, lines_per_chunk=CHUNK_LINES, overlap_lines=CHUNK_LINE_OVERLAP):
    lines = text.split("\n")
    docs = []
    total_lines = len(lines)
    chapters = extract_chapter_metadata(text)

    # 如果清洗后只剩一大段没有换行，直接按字符块兜底，避免整篇只生�?1 �?chunk
    if total_lines <= 1:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
        )
        chunks = splitter.split_text(text)
        for chunk_index, chunk_text in enumerate(chunks):
            chunk_text = chunk_text.strip()
            if not chunk_text:
                continue
            if len(chunk_text) > MAX_CHUNK_CHARS:
                chunk_text = chunk_text[:MAX_CHUNK_CHARS]
            docs.append(
                Document(
                    page_content=chunk_text,
                    metadata={
                        "chunk_index": chunk_index,
                        "start_line": 1,
                        "end_line": 1,
                        "total_lines": total_lines,
                        "chapter": "未知章节",
                        "split_mode": "char_fallback",
                    },
                )
            )
        logger.info(
            "split_text_by_lines: used char fallback, created %s chunks from %s line(s)",
            len(docs),
            total_lines,
        )
        return docs

    i = 0
    chunk_index = 0
    while i < total_lines:
        end = min(i + lines_per_chunk, total_lines)
        chunk_lines = lines[i:end]

        current_chapter = None
        for chapter in chapters:
            if chapter["start_line"] <= i + 1 <= chapter["end_line"]:
                current_chapter = chapter["title"]
                break

        chunk_text = "\n".join(chunk_lines).strip()
        if len(chunk_text) > MAX_CHUNK_CHARS:
            chunk_text = chunk_text[:MAX_CHUNK_CHARS]

        metadata = {
            "chunk_index": chunk_index,
            "start_line": i + 1,
            "end_line": end,
            "total_lines": total_lines,
            "chapter": current_chapter if current_chapter else "未知章节",
        }

        docs.append(Document(page_content=chunk_text, metadata=metadata))
        chunk_index += 1

        if i + lines_per_chunk < total_lines:
            i += lines_per_chunk - overlap_lines
        else:
            break

    logger.info("split_text_by_lines: created %s chunks from %s lines", len(docs), total_lines)
    return docs


def _reset_persisted_store():
    if PERSIST_DIR.exists():
        shutil.rmtree(PERSIST_DIR)


def create_vector_store(text, mode="new"):
    has_existing_index = False
    embeddings = get_embeddings()
    logger.info("create_vector_store: input_chars=%s, mode=%s", len(text), mode)

    # 基础文本清洗
    text = clean_text(text)

    docs = split_text_by_lines(text)
    logger.info("create_vector_store: chunks=%s", len(docs))

    # 检查是否存在现有索�?    has_existing_index = PERSIST_DIR.exists()

    if mode == "new":
        # 新建索引：只在没有现有索引时创建
        if has_existing_index:
            raise RuntimeError(
                "当前已存在索引，请选择'覆盖现有索引'模式或先清空向量�?"
            )
    elif mode == "overwrite":
        # 覆盖现有索引：无条件清空并重新创�?        if has_existing_index:
        logger.info("create_vector_store: overwriting existing index")
        _reset_persisted_store()

    vectordb = None
    total_batches = (len(docs) + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE

    for batch_idx in range(total_batches):
        start_idx = batch_idx * EMBED_BATCH_SIZE
        end_idx = min(start_idx + EMBED_BATCH_SIZE, len(docs))
        batch_docs = docs[start_idx:end_idx]
        logger.info("create_vector_store: batch %s/%s", batch_idx + 1, total_batches)

        for retry in range(EMBED_MAX_RETRIES):
            try:
                if vectordb is None:
                    vectordb = Chroma.from_documents(
                        batch_docs,
                        embedding=embeddings,
                        persist_directory=str(PERSIST_DIR),
                        collection_metadata={"hnsw:space": "cosine"},
                    )
                    logger.info("create_vector_store: initial Chroma index created")
                else:
                    vectordb.add_documents(batch_docs)
                    logger.info("create_vector_store: batch %s added", batch_idx + 1)

                break
            except Exception as e:
                logger.warning("batch %s retry %s failed: %s", batch_idx + 1, retry + 1, e)
                if retry < EMBED_MAX_RETRIES - 1:
                    time.sleep(2 ** retry)
                else:
                    raise RuntimeError(
                        f"创建向量存储失败（批�?{batch_idx + 1}/{total_batches}）：{e}\n"
                        f"建议：减�?EMBED_BATCH_SIZE 或增�?EMBED_TIMEOUT"
                    ) from e

    logger.info("create_vector_store: Chroma index ready with %s chunks", len(docs))
    return vectordb


def clear_vector_store(vectordb):
    if vectordb is not None:
        collection = vectordb._client.get_collection(vectordb._collection.name)
        count = collection.count()
        collection.delete(ids=collection.get()["ids"])
        logger.info("clear_vector_store: deleted %s documents", count)


def get_vector_store_stats(vectordb):
    if vectordb is None:
        return {"document_count": 0}

    collection = vectordb._client.get_collection(vectordb._collection.name)
    return {"document_count": collection.count()}


def retrieve(vectordb, query):
    logger.info("retrieve: query=%s", query)
    out = vectordb.similarity_search_with_score(query, k=RETRIEVE_TOP_K)
    logger.info("retrieve: hits=%s", len(out))

    results_with_score = []
    min_distance = float("inf")
    for doc, distance in out:
        logger.debug("retrieve: doc chunk preview='%s...', distance=%s", doc.page_content[:50], distance)
        results_with_score.append({"document": doc, "distance": distance})
        min_distance = min(min_distance, distance)

    logger.info(
        "retrieve: min_distance=%s, soft_threshold=%s, hard_threshold=%s",
        min_distance,
        SIMILARITY_THRESHOLD,
        SOFT_REJECTION_THRESHOLD,
    )

    if min_distance > SOFT_REJECTION_THRESHOLD:
        logger.info("retrieve: no matching results below hard threshold, rejecting (min_distance=%s)", min_distance)
        return {"reject": True, "message": REJECTION_MESSAGE, "min_distance": min_distance, "soft_reject": False}

    results_with_score.sort(key=lambda x: x["distance"])
    filtered_results = [r for r in results_with_score if r["distance"] <= SOFT_REJECTION_THRESHOLD]
    logger.info("retrieve: filtered to %s relevant results", len(filtered_results))

    if min_distance > SIMILARITY_THRESHOLD:
        logger.info("retrieve: results below hard threshold but above soft threshold, soft rejecting (min_distance=%s)",
                    min_distance)
        return {
            "reject": False,
            "results": filtered_results,
            "min_distance": min_distance,
            "soft_reject": True,
            "soft_message": SOFT_REJECTION_MESSAGE,
        }

    return {"reject": False, "results": filtered_results, "min_distance": min_distance, "soft_reject": False}

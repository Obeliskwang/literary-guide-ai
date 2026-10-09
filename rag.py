import logging
import re
import shutil
import time
from pathlib import Path

from chromadb.utils import embedding_functions
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from reranker import rerank_chunks

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
    USE_RERANKER,
    RERANKER_RECALL_K,
    RERANKER_TOP_N,
)
from llm import get_embeddings

logger = logging.getLogger(__name__)

PERSIST_ROOT = Path("chroma_db")


def get_book_persist_dir(book_id):
    """获取书籍的向量库持久化目录"""
    return PERSIST_ROOT / f"book_{book_id}"


def _reset_persisted_store(book_id):
    """重置指定书籍的向量库"""
    persist_dir = get_book_persist_dir(book_id)
    if persist_dir.exists():
        shutil.rmtree(persist_dir)


def clean_text(text):
    """基础文本清洗：统一换行、压缩空白、过滤广告行。适配RAG分块，抹平所有段落换行"""
    if not text:
        return text

    text = text.replace("\r\n", "\n").replace("\r", "\n")

    ad_patterns = [
        r"^.{0,5}(广告|推广|赞助|招商|加盟|招聘|诚聘).{0,20}$",
        r"^.{0,10}(http|https|www\.|\.com|\.cn).{0,30}$",
        r"^\s*\[.*?(广告|推广|赞助).*\]\s*$",
        r"^\s*(关注|扫码|点击|微信|联系我).{0,20}$",
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
        r"^\s*[一二三四五六七八九十\d]+\s*[回]?",
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


def split_text_by_lines(
    text,
    lines_per_chunk=CHUNK_LINES,
    overlap_lines=CHUNK_LINE_OVERLAP,
    source_format="txt",
):
    if source_format == "pdf":
        pages = text.split("\f")
        docs = []
        for page_num, page_text in enumerate(pages, 1):
            page_text = page_text.strip()
            if not page_text:
                continue
            if len(page_text) > MAX_CHUNK_CHARS:
                page_text = page_text[:MAX_CHUNK_CHARS]
            docs.append(
                Document(
                    page_content=page_text,
                    metadata={
                        "chunk_index": page_num - 1,
                        "page": page_num,
                        "chapter": f"第{page_num}页",
                        "source_format": "pdf",
                        "split_mode": "page_based",
                    },
                )
            )
        logger.info(
            "split_text_by_lines: PDF page-based split, created %s chunks from %s pages",
            len(docs),
            len(pages),
        )
        return docs

    lines = text.split("\n")
    docs = []
    total_lines = len(lines)
    chapters = extract_chapter_metadata(text)

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
                        "source_format": source_format,
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
            "source_format": source_format,
        }

        docs.append(Document(page_content=chunk_text, metadata=metadata))
        chunk_index += 1

        if i + lines_per_chunk < total_lines:
            i += lines_per_chunk - overlap_lines
        else:
            break

    logger.info(
        "split_text_by_lines: created %s chunks from %s lines", len(docs), total_lines
    )
    return docs


def create_vector_store(text, book_id, file_id, file_name, mode="append"):
    """为指定书籍和文件创建/追加向量"""
    embeddings = get_embeddings()
    persist_dir = get_book_persist_dir(book_id)

    source_format = file_name.lower().split(".")[-1] if file_name else "txt"

    logger.info(
        "create_vector_store: book_id=%s, file_id=%s, file_name=%s, input_chars=%s, mode=%s, format=%s",
        book_id,
        file_id,
        file_name,
        len(text),
        mode,
        source_format,
    )

    text = clean_text(text)
    docs = split_text_by_lines(text, source_format=source_format)
    logger.info("create_vector_store: chunks=%s", len(docs))

    for doc in docs:
        doc.metadata["book_id"] = book_id
        doc.metadata["file_id"] = file_id
        doc.metadata["file_name"] = file_name

    has_existing_index = persist_dir.exists()

    if mode == "new":
        if has_existing_index:
            raise RuntimeError("当前书籍已存在索引，请选择'追加'模式或先删除书籍")
    elif mode == "overwrite":
        if has_existing_index:
            logger.info("create_vector_store: overwriting existing index")
            _reset_persisted_store(book_id)

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
                        persist_directory=str(persist_dir),
                        collection_metadata={"hnsw:space": "cosine"},
                    )
                    logger.info(
                        "create_vector_store: initial Chroma index created for book %s",
                        book_id,
                    )
                else:
                    vectordb.add_documents(batch_docs)
                    logger.info("create_vector_store: batch %s added", batch_idx + 1)

                break
            except Exception as e:
                logger.warning(
                    "batch %s retry %s failed: %s", batch_idx + 1, retry + 1, e
                )
                if retry < EMBED_MAX_RETRIES - 1:
                    time.sleep(2**retry)
                else:
                    raise RuntimeError(
                        f"创建向量存储失败（批次{batch_idx + 1}/{total_batches}）：{e}\n"
                        f"建议：减少 EMBED_BATCH_SIZE 或增加 EMBED_TIMEOUT"
                    ) from e

    logger.info(
        "create_vector_store: Chroma index ready with %s chunks for book %s",
        len(docs),
        book_id,
    )
    return vectordb, len(docs)


def get_vector_store_by_book(book_id):
    """获取指定书籍的向量库"""
    persist_dir = get_book_persist_dir(book_id)
    if not persist_dir.exists():
        return None

    embeddings = get_embeddings()
    vectordb = Chroma(
        persist_directory=str(persist_dir),
        embedding_function=embeddings,
        collection_metadata={"hnsw:space": "cosine"},
    )
    return vectordb


def delete_file_chunks(book_id, file_id):
    """删除指定文件的所有分块向量"""
    vectordb = get_vector_store_by_book(book_id)
    if vectordb is None:
        return 0

    collection = vectordb._client.get_collection(vectordb._collection.name)
    all_data = collection.get()

    file_ids_to_delete = []
    for idx, metadata in enumerate(all_data["metadatas"]):
        if metadata.get("file_id") == file_id:
            file_ids_to_delete.append(all_data["ids"][idx])

    if file_ids_to_delete:
        collection.delete(ids=file_ids_to_delete)
        logger.info(
            "delete_file_chunks: deleted %s chunks for file %s",
            len(file_ids_to_delete),
            file_id,
        )

    return len(file_ids_to_delete)


def delete_book_vector_store(book_id):
    """删除书籍的整个向量库"""
    _reset_persisted_store(book_id)
    logger.info("delete_book_vector_store: deleted vector store for book %s", book_id)


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


def get_vector_store_stats_for_book(book_id):
    """获取指定书籍的向量库统计信息"""
    vectordb = get_vector_store_by_book(book_id)
    if vectordb is None:
        return {"document_count": 0}

    collection = vectordb._client.get_collection(vectordb._collection.name)
    return {"document_count": collection.count()}


def retrieve(vectordb, query):
    logger.info("retrieve: query=%s", query)

    recall_k = RERANKER_RECALL_K if USE_RERANKER else RETRIEVE_TOP_K
    out = vectordb.similarity_search_with_score(query, k=recall_k)
    logger.info(
        "retrieve: hits=%s (recall_k=%d, reranker=%s)", len(out), recall_k, USE_RERANKER
    )

    results_with_score = []
    min_distance = float("inf")
    for doc, distance in out:
        logger.debug(
            "retrieve: doc chunk preview='%s...', distance=%s",
            doc.page_content[:50],
            distance,
        )
        results_with_score.append({"document": doc, "distance": distance})
        min_distance = min(min_distance, distance)

    logger.info(
        "retrieve: min_distance=%s, soft_threshold=%s, hard_threshold=%s",
        min_distance,
        SIMILARITY_THRESHOLD,
        SOFT_REJECTION_THRESHOLD,
    )

    if min_distance > SOFT_REJECTION_THRESHOLD:
        logger.info(
            "retrieve: no matching results below hard threshold, rejecting (min_distance=%s)",
            min_distance,
        )
        return {
            "reject": True,
            "message": REJECTION_MESSAGE,
            "min_distance": min_distance,
            "soft_reject": False,
        }

    results_with_score.sort(key=lambda x: x["distance"])
    filtered_results = [
        r for r in results_with_score if r["distance"] <= SOFT_REJECTION_THRESHOLD
    ]
    logger.info("retrieve: filtered to %s relevant results", len(filtered_results))

    if USE_RERANKER and filtered_results:

        reranked = rerank_chunks(query, filtered_results, top_n=RERANKER_TOP_N)
        if reranked and "rerank_score" in reranked[0]:
            logger.info(
                "retrieve: reranker applied, %d -> %d chunks, top_score=%.4f",
                len(filtered_results),
                len(reranked),
                reranked[0]["rerank_score"],
            )
            filtered_results = reranked

    if min_distance > SIMILARITY_THRESHOLD:
        logger.info(
            "retrieve: results below hard threshold but above soft threshold, soft rejecting (min_distance=%s)",
            min_distance,
        )
        return {
            "reject": False,
            "results": filtered_results,
            "min_distance": min_distance,
            "soft_reject": True,
            "soft_message": SOFT_REJECTION_MESSAGE,
        }

    return {
        "reject": False,
        "results": filtered_results,
        "min_distance": min_distance,
        "soft_reject": False,
    }

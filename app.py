import hashlib
import logging
import time

import streamlit as st

from config import setup_logging
from ollama_check import OllamaModelsError, ensure_ollama_models

setup_logging()

logger = logging.getLogger(__name__)

st.set_page_config(page_title="伴读精灵", layout="wide")

try:
    ensure_ollama_models()
except OllamaModelsError as e:
    st.error(str(e))
    st.stop()

from rag import create_vector_store
from agent import generate_answer

st.title("📚 伴读精灵 - 经典文学名著导赏系统")

if "vectordb" not in st.session_state:
    st.session_state.vectordb = None

if "current_book" not in st.session_state:
    st.session_state.current_book = ""

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

uploaded_file = st.file_uploader("上传名著文本文件（TXT格式）", type="txt")

if uploaded_file:
    uploaded_file.seek(0)
    raw = uploaded_file.read()
    name = getattr(uploaded_file, "name", "upload")
    content_hash = hashlib.sha256(raw).hexdigest()
    
    if st.session_state.get("rag_content_hash") != content_hash:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("gbk")
            except:
                st.error("文件编码异常，请使用 UTF-8 或 GBK 格式")
                st.stop()
        
        logger.info(
            "RAG upload (new or replaced file): file=%r bytes=%s chars=%s",
            name,
            len(raw),
            len(text),
        )
        
        with st.spinner("正在处理文件..."):
            st.session_state.vectordb = create_vector_store(text)
            st.session_state.rag_content_hash = content_hash
            st.session_state.current_book = name
            st.session_state.chat_history = []
        
        st.success(f"《{name}》已成功入库，可以开始提问！")
    else:
        logger.debug(
            "RAG: reusing indexed corpus (same bytes as last index), file=%r",
            name,
        )

if st.session_state.current_book:
    st.subheader(f"当前名著：《{st.session_state.current_book}》")

user_input = st.chat_input("请输入您的问题...")

if user_input:
    if st.session_state.vectordb is None:
        st.warning("请先上传名著文本文件")
    else:
        preview = user_input if len(user_input) <= 500 else user_input[:500] + "…"
        logger.info(
            "Chat invoke: chars=%s preview=%r",
            len(user_input),
            preview,
        )
        
        with st.spinner("正在检索原著..."):
            t0 = time.perf_counter()
            
            result = generate_answer(st.session_state.vectordb, user_input)
            
            elapsed = time.perf_counter() - t0
            logger.info(
                "Chat done: %.2fs, rejected=%s",
                elapsed,
                result.get("rejected"),
            )
        
        st.session_state.chat_history.append({
            "question": user_input,
            "answer": result["answer"],
            "sources": result.get("sources", []),
            "rejected": result.get("rejected", False),
            "min_distance": result.get("min_distance", 0)
        })

for i, chat in enumerate(st.session_state.chat_history):
    st.write(f"---")
    st.write(f"**问：** {chat['question']}")
    
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.subheader("🤖 AI 回答")
        if chat["rejected"]:
            st.warning(chat["answer"])
        else:
            st.write(chat["answer"])
            st.write(f"距离值: {chat.get('min_distance', 0):.4f}（越小越相似）")
    
    with col2:
        st.subheader("📖 原著依据")
        if chat["sources"]:
            for j, source in enumerate(chat["sources"]):
                if j < 3:
                    st.write(f"**片段{j+1}**（距离: {source['distance']:.4f}）")
                    st.write(f"> {source['text'][:300]}{'...' if len(source['text']) > 300 else ''}")
        else:
            st.write("无匹配原文")

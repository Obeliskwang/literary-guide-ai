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

from rag import create_vector_store, clear_vector_store, get_vector_store_stats
from agent import generate_answer

# 初始化会话状态
def init_session_state():
    if "vectordb" not in st.session_state:
        st.session_state.vectordb = None
    if "current_book" not in st.session_state:
        st.session_state.current_book = ""
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "rag_content_hash" not in st.session_state:
        st.session_state.rag_content_hash = ""

init_session_state()

# 页面标题
st.title("📚 伴读精灵 - 经典文学名著导赏系统")

# 侧边栏：文档上传与向量库管理
with st.sidebar:
    st.header("📁 文档管理")
    
    # 文件上传
    uploaded_file = st.file_uploader("上传名著文本文件（TXT格式）", type="txt")
    
    # 入库模式选择
    mode_options = {
        "new": "新建索引",
        "overwrite": "覆盖现有索引",
        "append": "追加到现有索引"
    }
    selected_mode = st.selectbox("入库模式", list(mode_options.keys()), format_func=lambda x: mode_options[x])
    
    # 上传按钮
    if uploaded_file and st.button("📥 开始入库"):
        uploaded_file.seek(0)
        raw = uploaded_file.read()
        name = getattr(uploaded_file, "name", "upload")
        content_hash = hashlib.sha256(raw).hexdigest()
        
        # 格式校验
        if len(raw) == 0:
            st.error("文件为空，请选择有效的文本文件")
        elif len(raw) > 50 * 1024 * 1024:  # 50MB限制
            st.error("文件过大，建议不超过50MB")
        else:
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    text = raw.decode("gbk")
                except:
                    st.error("文件编码异常，请使用 UTF-8 或 GBK 格式")
                    st.stop()
            
            logger.info(
                "RAG upload (new or replaced file): file=%r bytes=%s chars=%s mode=%s",
                name, len(raw), len(text), selected_mode
            )
            
            with st.spinner("正在处理文件..."):
                # 根据模式处理
                if selected_mode == "overwrite" and st.session_state.vectordb is not None:
                    clear_vector_store(st.session_state.vectordb)
                
                st.session_state.vectordb = create_vector_store(text, mode=selected_mode)
                st.session_state.rag_content_hash = content_hash
                st.session_state.current_book = name
                st.session_state.chat_history = []
            
            st.success(f"《{name}》已成功入库，可以开始提问！")
    
    # 向量库管理
    st.header("🗄️ 向量库管理")
    
    # 显示统计信息
    stats = get_vector_store_stats(st.session_state.vectordb)
    st.info(f"当前索引文档数: **{stats['document_count']}**")
    
    if st.session_state.current_book:
        st.info(f"当前名著: **{st.session_state.current_book}**")
    
    # 清空按钮
    if st.button("🗑️ 清空向量库"):
        if st.session_state.vectordb is not None:
            clear_vector_store(st.session_state.vectordb)
            st.session_state.vectordb = None
            st.session_state.current_book = ""
            st.session_state.chat_history = []
            st.session_state.rag_content_hash = ""
            st.success("向量库已清空")
        else:
            st.warning("向量库为空")

# 主内容区：问答界面
st.header("💬 智能问答")

# 显示当前名著
if st.session_state.current_book:
    st.subheader(f"当前阅读：《{st.session_state.current_book}》")

# 问答区域
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
            "soft_reject": result.get("soft_reject", False),
            "min_distance": result.get("min_distance", 0)
        })

# 显示对话历史
for i, chat in enumerate(st.session_state.chat_history):
    st.write(f"---")
    st.write(f"**问：** {chat['question']}")
    
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.subheader("🤖 AI 回答")
        if chat["rejected"]:
            st.warning(chat["answer"])
        else:
            if chat.get("soft_reject"):
                st.info("⚠️ 相关性较低：以下回答基于有限的原著信息")
            st.write(chat["answer"])
            st.write(f"相似度: {(1 - chat.get('min_distance', 0)) * 100:.1f}%")
    
    with col2:
        st.subheader("📖 原著依据")
        if chat["sources"]:
            for j, source in enumerate(chat["sources"]):
                if j < 3:
                    chapter = source.get("metadata", {}).get("chapter", "未知章节")
                    st.write(f"**片段{j+1}**（{chapter}）")
                    st.write(f"> {source['text'][:300]}{'...' if len(source['text']) > 300 else ''}")
        else:
            st.write("无匹配原文")

# 显示阈值说明
with st.expander("🔍 检索阈值说明"):
    st.write("""
    - **相似度阈值**: 0.7（距离值），超过此值进入软拒答状态
    - **完全拒答阈值**: 1.0（距离值），超过此值完全拒答
    - **召回段落数**: 8段
    - **说明**: Chroma使用余弦相似度，距离值越小越相似（0-2范围）
    """)

import hashlib
import logging
import time
import re
import streamlit as st

# ========== 导入区 ==========
from config import setup_logging
from ollama_check import OllamaModelsError, ensure_ollama_models
from rag import create_vector_store, clear_vector_store, get_vector_store_stats
from agent import generate_answer
from character_service import (
    get_characters,
    get_character_by_id,
    get_character_relations,
    generate_mermaid_graph,
    generate_mermaid_graph_family,
    get_book_title,
    get_all_families,
    get_characters_by_family,
    get_events,
    get_character_events,
)
from utils import render_mermaid  # 导入自定义渲染函数

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(page_title="伴读精灵", layout="wide")

try:
    ensure_ollama_models()
except OllamaModelsError as e:
    st.error(str(e))
    st.stop()


# ========== 初始化会话状态 ==========
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

# ========== 页面导航 ==========
page = st.sidebar.selectbox("选择页面", ["智能问答", "人物关系"])
st.title("伴读精灵 - 经典文学名著导赏系统")

# ========== 智能问答页面 ==========
if page == "智能问答":
    # 侧边栏：文档上传与向量库管理
    with st.sidebar:
        st.header("文档管理")

        uploaded_file = st.file_uploader("上传名著文本文件（TXT格式）", type="txt")

        mode_options = {
            "new": "新建索引",
            "overwrite": "覆盖现有索引",
            "append": "追加到现有索引",
        }
        selected_mode = st.selectbox(
            "入库模式", list(mode_options.keys()), format_func=lambda x: mode_options[x]
        )

        if uploaded_file and st.button("开始入库"):
            uploaded_file.seek(0)
            raw = uploaded_file.read()
            name = getattr(uploaded_file, "name", "upload")
            content_hash = hashlib.sha256(raw).hexdigest()

            if len(raw) == 0:
                st.error("文件为空，请选择有效的文本文件")
            elif len(raw) > 50 * 1024 * 1024:
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
                    name,
                    len(raw),
                    len(text),
                    selected_mode,
                )

                with st.spinner("正在处理文件..."):
                    if (
                        selected_mode == "overwrite"
                        and st.session_state.vectordb is not None
                    ):
                        clear_vector_store(st.session_state.vectordb)

                    st.session_state.vectordb = create_vector_store(
                        text, mode=selected_mode
                    )
                    st.session_state.rag_content_hash = content_hash
                    st.session_state.current_book = name
                    st.session_state.chat_history = []

                st.success(f"《{name}》已成功入库，可以开始提问！")

        st.header("向量库管理")
        stats = get_vector_store_stats(st.session_state.vectordb)
        st.info(f"当前索引文档数: {stats['document_count']}")

        if st.session_state.current_book:
            st.info(f"当前名著: {st.session_state.current_book}")

        if st.button("清空向量库"):
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
    st.header("智能问答")

    if st.session_state.current_book:
        st.subheader(f"当前阅读：《{st.session_state.current_book}》")

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
                result = generate_answer(
                    st.session_state.vectordb,
                    user_input,
                    conversation_history=st.session_state.chat_history,
                )
                elapsed = time.perf_counter() - t0
                logger.info(
                    "Chat done: %.2fs, rejected=%s",
                    elapsed,
                    result.get("rejected"),
                )

            st.session_state.chat_history.append(
                {
                    "question": user_input,
                    "answer": result["answer"],
                    "sources": result.get("sources", []),
                    "rejected": result.get("rejected", False),
                    "soft_reject": result.get("soft_reject", False),
                    "min_distance": result.get("min_distance", 0),
                }
            )

    for i, chat in enumerate(st.session_state.chat_history):
        st.write("---")
        st.write(f"问：{chat['question']}")

        col1, col2 = st.columns([3, 2])

        with col1:
            st.subheader("AI 回答")
            if chat["rejected"]:
                st.warning(chat["answer"])
            else:
                if chat.get("soft_reject"):
                    st.info("相关性较低：以下回答基于有限的原著信息")
                st.write(chat["answer"])
                st.write(f"相似度: {(1 - chat.get('min_distance', 0)) * 100:.1f}%")

        with col2:
            st.subheader("原著依据")
            if chat["sources"]:
                for j, source in enumerate(chat["sources"]):
                    if j < 3:
                        chapter = source.get("metadata", {}).get("chapter", "未知章节")
                        st.write(f"片段{j+1}（{chapter}）")
                        st.write(
                            f"> {source['text'][:300]}{'...' if len(source['text']) > 300 else ''}"
                        )
            else:
                st.write("无匹配原文")

    with st.expander("检索阈值说明"):
        st.write(
            """
        - 相似度阈值: 1.0（距离值），超过此值进入软拒答状态
        - 完全拒答阈值: 2.0（距离值），超过此值完全拒答
        - 召回段落数: 3段
        - 说明: Chroma使用余弦相似度，距离值越小越相似（0-2范围）
        """
        )

# ========== 人物关系页面 ==========
elif page == "人物关系":
    book_title = get_book_title()
    if book_title:
        st.subheader(f"《{book_title}》人物关系")

    # 人物列表
    st.header("人物列表")

    families = get_all_families()
    selected_family = st.selectbox("按家族筛选", ["全部"] + families)

    if selected_family == "全部":
        characters = get_characters()
    else:
        characters = get_characters_by_family(selected_family)

    cols = st.columns(3)
    for idx, char in enumerate(characters):
        with cols[idx % 3]:
            with st.expander(f"{char['name']} - {char['identity']}"):
                st.write(f"**身份**: {char['identity']}")
                st.write(f"**家族**: {char.get('family', '未知')}")
                st.write(f"**简介**: {char.get('description', '')}")

                relations = get_character_relations(char["id"])
                if relations:
                    st.write("**关联角色**:")
                    for rel in relations:
                        st.write(f"- {rel['target_name']}：{rel['relation']}")

    # ========== 人物关系图 ==========
    st.header("人物关系图")

    graph_mode = st.selectbox(
        "选择关系图类型", ["取经团队关系", "孙悟空关系网", "天庭人物关系"]
    )

    if graph_mode == "取经团队关系":
        mermaid_code = generate_mermaid_graph_family()
    elif graph_mode == "孙悟空关系网":
        mermaid_code = generate_mermaid_graph("sun_wukong")
    elif graph_mode == "天庭人物关系":
        mermaid_code = generate_mermaid_graph("jade_emperor")

    # ========== 使用 render_mermaid 渲染 ==========
    # 显示源码（调试用）
    with st.expander("📄 查看 Mermaid 源码"):
        st.code(mermaid_code, language="mermaid")

    # 使用自定义渲染函数
    st.markdown("### 📊 关系图")
    render_mermaid(mermaid_code, height="600px")

    # ========== 核心事件表 ==========
    st.header("核心事件表")

    events = get_events()
    if events:
        for event in events:
            with st.expander(f"{event['name']} - {event['chapter']}"):
                st.write(f"**章节**: {event['chapter']}")
                st.write(f"**描述**: {event['description']}")
                st.write("**涉及人物**:")
                char_names = []
                for char_id in event["characters"]:
                    char = get_character_by_id(char_id)
                    if char:
                        char_names.append(char["name"])
                st.write(", ".join(char_names))

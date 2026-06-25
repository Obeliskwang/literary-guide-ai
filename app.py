# -*- coding: utf-8 -*-
import logging
import time
import streamlit as st

from config import setup_logging
from ollama_check import OllamaModelsError, ensure_ollama_models
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
from utils import render_mermaid
from book_manager import init_book_session_state, render_bookshelf_sidebar, render_book_manager_dialog

setup_logging()
logger = logging.getLogger(__name__)

st.set_page_config(page_title="伴读精灵", layout="wide")
st.markdown(
    """
<style>
* {font-family: "SimHei", "Microsoft YaHei", sans-serif !important;}
</style>
""",
    unsafe_allow_html=True,
)

try:
    ensure_ollama_models()
except OllamaModelsError as e:
    st.error(str(e))
    st.stop()


def init_session_state():
    init_book_session_state()
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "rag_content_hash" not in st.session_state:
        st.session_state.rag_content_hash = ""
    if "character_tab" not in st.session_state:
        st.session_state.character_tab = "人物列表"


init_session_state()

page = st.sidebar.selectbox("选择页面", ["智能问答", "人物关系"])
st.title("伴读精灵 - 经典文学名著导赏问答系统")

render_book_manager_dialog()


if page == "智能问答":
    with st.sidebar:
        render_bookshelf_sidebar()

    st.header("智能问答")

    if st.session_state.current_book:
        st.subheader(f"当前阅读：《{st.session_state.current_book}》")

    user_input = st.chat_input("请输入你的问题...")

    if user_input:
        if st.session_state.vectordb is None:
            st.warning("请先创建书籍并上传文件")
        else:
            preview = user_input if len(user_input) <= 500 else user_input[:500] + "..."
            logger.info(
                "Chat invoke: chars=%s preview=%r",
                len(user_input),
                preview,
            )

            with st.spinner("正在检索原文..."):
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
                    st.info("相关度较低：以下回答基于有限原文信息")
                st.write(chat["answer"])
                st.write(f"相似度：{(1 - chat.get('min_distance', 0)) * 100:.1f}%")

        with col2:
            st.subheader("原文依据")
            if chat["sources"]:
                for j, source in enumerate(chat["sources"]):
                    if j < 3:
                        chapter = source.get("metadata", {}).get("chapter", "未知章节")
                        file_name = source.get("metadata", {}).get("file_name", "未知文件")
                        st.write(f"片段{j+1}：{file_name} - {chapter}")
                        st.write(
                            f"> {source['text'][:300]}{'...' if len(source['text']) > 300 else ''}"
                        )
            else:
                st.write("无匹配原文")

    with st.expander("检索阈值说明"):
        st.write(
            """
        - 相似度软阈值：1.0（距离值），超过此值进入弱拒绝模式
        - 完全拒绝阈值：2.0（距离值），超过此值直接拒绝回答
        - 返回片段数量：3段
        - 说明：Chroma使用余弦相似度，距离值越小越相似，范围0~2
        """
        )

elif page == "人物关系":
    if "character_tab" not in st.session_state:
        st.session_state.character_tab = "人物列表"
    character_tab = st.session_state.character_tab

    st.sidebar.markdown("---")
    st.sidebar.markdown("**功能选择**")

    if st.sidebar.button(
        "人物列表",
        key="btn_char_list",
        use_container_width=True,
        type="primary" if character_tab == "人物列表" else "secondary",
    ):
        character_tab = "人物列表"
        st.session_state.character_tab = "人物列表"

    if st.sidebar.button(
        "关系图",
        key="btn_graph",
        use_container_width=True,
        type="primary" if character_tab == "人物关系图" else "secondary",
    ):
        character_tab = "人物关系图"
        st.session_state.character_tab = "人物关系图"

    if st.sidebar.button(
        "事件表",
        key="btn_events",
        use_container_width=True,
        type="primary" if character_tab == "核心事件表" else "secondary",
    ):
        character_tab = "核心事件表"
        st.session_state.character_tab = "核心事件表"

    book_title = get_book_title()
    if book_title:
        st.subheader(f"《{book_title}》人物关系")

    if character_tab == "人物列表":
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
                    st.write(f"**身份**：{char['identity']}")
                    st.write(f"**家族**：{char.get('family', '未知')}")
                    st.write(f"**简介**：{char.get('description', '')}")

                    relations = get_character_relations(char["id"])
                    if relations:
                        st.write("**关联角色**：")
                        for rel in relations:
                            st.write(f"- {rel['target_name']}：{rel['relation']}")

    elif character_tab == "人物关系图":
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

        with st.expander("查看 Mermaid 源码"):
            st.code(mermaid_code, language="mermaid")

        st.markdown("### 关系图")
        render_mermaid(mermaid_code, height="600px")

    elif character_tab == "核心事件表":
        st.header("核心事件表")

        events = get_events()
        if events:
            for event in events:
                with st.expander(f"{event['name']} - {event['chapter']}"):
                    st.write(f"**章节**：{event['chapter']}")
                    st.write(f"**描述**：{event['description']}")
                    st.write("**涉及人物**：")
                    char_names = []
                    for char_id in event["characters"]:
                        char = get_character_by_id(char_id)
                        if char:
                            char_names.append(char["name"])
                    st.write(", ".join(char_names))

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
from exercise_service import (
    get_exercises,
    get_exercise_by_id,
    get_all_chapters,
    get_book_title as get_exercises_book_title,
    get_total_count,
)
from utils import render_mermaid
from book_manager import (
    init_book_session_state,
    render_bookshelf_sidebar,
    render_book_manager_dialog,
)

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

page = st.sidebar.selectbox("选择页面", ["智能问答", "人物关系", "练习题"])
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
                        file_name = source.get("metadata", {}).get(
                            "file_name", "未知文件"
                        )
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

elif page == "练习题":
    st.header("练习题")

    # 初始化练习题相关的session_state
    if "exercise_mode" not in st.session_state:
        st.session_state.exercise_mode = "做题"  # 做题 / 结果
    if "current_exercise_index" not in st.session_state:
        st.session_state.current_exercise_index = 0
    if "user_answers" not in st.session_state:
        st.session_state.user_answers = {}
    if "submitted" not in st.session_state:
        st.session_state.submitted = False

    book_title = get_exercises_book_title()
    if book_title:
        st.subheader(f"《{book_title}》练习题")

    # 加载所有题目
    all_exercises = get_exercises()
    total_count = len(all_exercises)

    if total_count == 0:
        st.info("暂无练习题")
    else:
        # 模式切换按钮
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button(
                "做题模式",
                use_container_width=True,
                type=(
                    "primary"
                    if st.session_state.exercise_mode == "做题"
                    else "secondary"
                ),
            ):
                st.session_state.exercise_mode = "做题"
                st.session_state.submitted = False
        with col2:
            if st.button(
                "查看结果",
                use_container_width=True,
                type=(
                    "primary"
                    if st.session_state.exercise_mode == "结果"
                    else "secondary"
                ),
            ):
                st.session_state.exercise_mode = "结果"

        st.markdown("---")

        if st.session_state.exercise_mode == "做题":
            # 做题模式
            st.write(f"题目总数：{total_count} 题")
            st.write(f"已作答：{len(st.session_state.user_answers)} 题")

            # 按章节筛选
            chapters = get_all_chapters()
            selected_chapter = st.selectbox("按章节筛选", ["全部"] + chapters)

            # 获取当前显示的题目列表
            if selected_chapter == "全部":
                display_exercises = all_exercises
            else:
                display_exercises = [
                    e for e in all_exercises if e.get("chapter") == selected_chapter
                ]

            if len(display_exercises) == 0:
                st.info("该章节暂无练习题")
            else:
                # 限制显示的题目数量
                max_display = 5
                display_count = min(len(display_exercises), max_display)
                st.write(f"显示前 {display_count} 题，共 {len(display_exercises)} 题")

                # 逐题显示
                for idx in range(display_count):
                    exercise = display_exercises[idx]
                    exercise_id = exercise["id"]

                    st.markdown(f"**题目 {idx + 1}** (ID: {exercise_id})")
                    st.write(f"章节：{exercise.get('chapter', '未知')}")
                    st.write(exercise["question"])

                    # 选项列表
                    options = exercise.get("options", [])

                    # 检查是否已作答
                    current_answer = st.session_state.user_answers.get(exercise_id)

                    # 根据是否提交显示不同的选择组件
                    if not st.session_state.submitted:
                        # 未提交时，显示radio让用户选择
                        selected_idx = st.radio(
                            "请选择答案",
                            options=range(len(options)),
                            format_func=lambda x: f"{chr(65 + x)}. {options[x]}",
                            key=f"radio_{exercise_id}",
                            index=current_answer if current_answer is not None else 0,
                        )

                        if selected_idx is not None:
                            st.session_state.user_answers[exercise_id] = selected_idx
                    else:
                        # 已提交时，显示答案对照
                        correct_idx = exercise["answer"]
                        for opt_idx, opt_text in enumerate(options):
                            col_a, col_b = st.columns([4, 1])
                            with col_a:
                                if opt_idx == correct_idx:
                                    st.success(
                                        f"{chr(65 + opt_idx)}. {opt_text} (正确答案)"
                                    )
                                elif (
                                    opt_idx == current_answer and opt_idx != correct_idx
                                ):
                                    st.error(
                                        f"{chr(65 + opt_idx)}. {opt_text} (你的答案 - 错误)"
                                    )
                                else:
                                    st.write(f"{chr(65 + opt_idx)}. {opt_text}")
                            with col_b:
                                pass

                        # 显示解析
                        st.info(f"**解析**：{exercise.get('explanation', '')}")

                    st.markdown("---")

                # 提交按钮
                if st.button("提交答案", type="primary", use_container_width=True):
                    st.session_state.submitted = True
                    st.rerun()

                # 进度提示
                answered_count = len(st.session_state.user_answers)
                progress = answered_count / total_count if total_count > 0 else 0
                st.progress(progress, text=f"已完成 {answered_count}/{total_count} 题")

        else:
            # 结果模式
            st.header("答题结果")

            if len(st.session_state.user_answers) == 0:
                st.info("请先完成做题后再查看结果")
            else:
                # 计算正确率
                correct_count = 0
                wrong_exercises = []

                for exercise_id, user_answer in st.session_state.user_answers.items():
                    exercise = get_exercise_by_id(exercise_id)
                    if exercise:
                        correct_idx = exercise["answer"]
                        if user_answer == correct_idx:
                            correct_count += 1
                        else:
                            wrong_exercises.append(exercise)

                total_answered = len(st.session_state.user_answers)
                accuracy = (
                    (correct_count / total_answered * 100) if total_answered > 0 else 0
                )

                # 显示统计信息
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("已作答", f"{total_answered} 题")
                with col2:
                    st.metric("正确", f"{correct_count} 题", delta_color="normal")
                with col3:
                    st.metric(
                        "正确率",
                        f"{accuracy:.1f}%",
                        delta_color="normal" if accuracy >= 60 else "inverse",
                    )

                st.markdown("---")

                # 显示错题列表
                if wrong_exercises:
                    st.subheader(f"错题分析 (共 {len(wrong_exercises)} 题)")

                    for idx, exercise in enumerate(wrong_exercises, 1):
                        user_answer = st.session_state.user_answers.get(exercise["id"])
                        correct_idx = exercise["answer"]
                        options = exercise.get("options", [])

                        with st.expander(f"错题 {idx}：{exercise['question'][:30]}..."):
                            st.write(f"**章节**：{exercise.get('chapter', '未知')}")
                            st.write(f"**题目**：{exercise['question']}")
                            st.write(
                                f"**你的答案**：{chr(65 + user_answer) if user_answer is not None else '未作答'}. {options[user_answer] if user_answer is not None and user_answer < len(options) else '无效答案'}"
                            )
                            st.write(
                                f"**正确答案**：{chr(65 + correct_idx)}. {options[correct_idx]}"
                            )
                            st.write(f"**解析**：{exercise.get('explanation', '')}")
                else:
                    st.success("恭喜！所有已作答的题目都正确！")

                # 重新开始按钮
                st.markdown("---")
                if st.button("重新开始", type="secondary", use_container_width=True):
                    st.session_state.exercise_mode = "做题"
                    st.session_state.current_exercise_index = 0
                    st.session_state.user_answers = {}
                    st.session_state.submitted = False
                    st.rerun()

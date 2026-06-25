# -*- coding: utf-8 -*-
"""
书籍管理模块

负责伴读精灵系统的多书籍管理功能，包括：
- 书籍元数据管理界面
- 书籍切换逻辑
- 侧边栏书架展示
- 文件上传与管理
"""

import hashlib
import logging

import streamlit as st

from utils import (
    load_books_metadata,
    save_books_metadata,
    create_new_book,
    add_file_to_book,
    remove_file_from_book,
    get_book_by_id,
    rename_book,
    delete_book,
    get_total_chunk_count,
)
from rag import (
    create_vector_store,
    get_vector_store_by_book,
    delete_file_chunks,
    delete_book_vector_store,
    get_vector_store_stats_for_book,
)

logger = logging.getLogger(__name__)


def _safe_rerun():
    """安全的 rerun 封装"""
    st.rerun()


def init_book_session_state():
    """初始化书籍管理相关的 session_state 变量"""
    if "vectordb" not in st.session_state:
        st.session_state.vectordb = None
    if "current_book" not in st.session_state:
        st.session_state.current_book = ""
    if "current_book_id" not in st.session_state:
        st.session_state.current_book_id = ""
    if "selected_book_id" not in st.session_state:
        st.session_state.selected_book_id = ""
    if "book_search_query" not in st.session_state:
        st.session_state.book_search_query = ""
    if "new_book_name" not in st.session_state:
        st.session_state.new_book_name = None
    if "book_list_page" not in st.session_state:
        st.session_state.book_list_page = 1
    if "editing_book_id" not in st.session_state:
        st.session_state.editing_book_id = ""
    if "editing_book_name" not in st.session_state:
        st.session_state.editing_book_name = ""
    if "delete_confirm_id" not in st.session_state:
        st.session_state.delete_confirm_id = ""
    if "delete_current_book_confirm" not in st.session_state:
        st.session_state.delete_current_book_confirm = False


def _book_matches_query(book, query):
    """判断书籍是否匹配搜索查询"""
    if not query or not query.strip():
        return True
    query = query.strip().lower()
    return query in book["name"].lower() or query in book["id"].lower()


def _decode_uploaded_text(raw):
    """尝试用多种编码解码上传的文本内容"""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            try:
                return raw.decode("gb2312")
            except Exception:
                return None


def select_book(book_id):
    """切换到指定书籍，更新状态并清空聊天历史"""
    book = get_book_by_id(book_id)
    if book:
        st.session_state.current_book_id = book_id
        st.session_state.current_book = book["name"]
        st.session_state.vectordb = get_vector_store_by_book(book_id)
        st.session_state.chat_history = []
        st.session_state.selected_book_id = book_id


PAGE_SIZE = 3


def _render_pagination(total_pages, key_prefix="book_list"):
    """渲染分页控件"""
    current_page = st.session_state.book_list_page
    cols = st.columns([1, 1, 1, 1, 1])

    with cols[0]:
        if st.button(
            "‹",
            key=f"{key_prefix}_prev",
            disabled=current_page <= 1,
            use_container_width=True,
        ):
            st.session_state.book_list_page = current_page - 1
            _safe_rerun()

    with cols[2]:
        st.markdown(
            f"<div style='text-align:center; padding:8px 0;'>{current_page} / {total_pages}</div>",
            unsafe_allow_html=True,
        )

    with cols[4]:
        if st.button(
            "›",
            key=f"{key_prefix}_next",
            disabled=current_page >= total_pages,
            use_container_width=True,
        ):
            st.session_state.book_list_page = current_page + 1
            _safe_rerun()


def _render_book_manager_content():
    """渲染书籍管理内容（用于popover或dialog）"""
    st.caption("搜索、创建、编辑、删除书籍知识库")

    query = st.text_input(
        "查询书籍",
        placeholder="输入书名或书籍ID实时筛选列表",
        key="book_search_input",
    )

    books = load_books_metadata()
    filtered_books = [b for b in books if _book_matches_query(b, query)]

    if query != st.session_state.book_search_query:
        st.session_state.book_search_query = query
        st.session_state.book_list_page = 1
        _safe_rerun()

    st.session_state.book_search_query = query

    col_new, col_spacer = st.columns([2, 3])
    with col_new:
        if st.button("新建书籍", use_container_width=True, type="primary"):
            st.session_state.new_book_name = ""
            _safe_rerun()

    if st.session_state.new_book_name is not None:
        st.markdown("##### 新建书籍")
        col_input, col_create, col_cancel = st.columns([3, 1, 1])
        with col_input:
            new_name = st.text_input(
                "书籍名称",
                value=st.session_state.new_book_name,
                placeholder="请输入新书名称",
                label_visibility="collapsed",
                key="new_book_name_input",
            )
        with col_create:
            if st.button("确认创建", use_container_width=True):
                if new_name.strip():
                    book_id = create_new_book(new_name.strip())
                    select_book(book_id)
                    st.success(f"书籍《{new_name.strip()}》已创建！")
                    st.session_state.new_book_name = None
                    _safe_rerun()
                else:
                    st.warning("请输入书籍名称")
        with col_cancel:
            if st.button("取消", use_container_width=True):
                st.session_state.new_book_name = None
                _safe_rerun()

    st.markdown("##### 书籍列表")
    if not filtered_books:
        st.info("没有找到匹配的书籍")
    else:
        total_pages = max(1, (len(filtered_books) + PAGE_SIZE - 1) // PAGE_SIZE)
        current_page = st.session_state.book_list_page

        if current_page > total_pages:
            st.session_state.book_list_page = total_pages
            current_page = total_pages

        start_idx = (current_page - 1) * PAGE_SIZE
        end_idx = start_idx + PAGE_SIZE
        page_books = filtered_books[start_idx:end_idx]

        selected_id = (
            st.session_state.selected_book_id or st.session_state.current_book_id
        )

        for book in page_books:
            is_selected = book["id"] == selected_id
            is_editing = book["id"] == st.session_state.editing_book_id

            with st.container():
                col_radio, col_name, col_count, col_edit, col_del = st.columns(
                    [0.5, 4, 1.5, 1, 1]
                )

                with col_radio:
                    if st.button(
                        "●" if is_selected else "○",
                        key=f"radio_{book['id']}",
                        use_container_width=True,
                    ):
                        st.session_state.selected_book_id = book["id"]
                        _safe_rerun()

                with col_name:
                    if is_editing:
                        edit_name = st.text_input(
                            "编辑书名",
                            value=st.session_state.editing_book_name,
                            label_visibility="collapsed",
                            key=f"edit_input_{book['id']}",
                        )
                    else:
                        st.markdown(
                            f"**{book['name']}**  \n<small>ID: {book['id']}</small>",
                            unsafe_allow_html=True,
                        )

                with col_count:
                    st.caption(f"[{len(book.get('files', []))}个文档]")

                with col_edit:
                    if is_editing:
                        if st.button(
                            "保存", key=f"save_{book['id']}", use_container_width=True
                        ):
                            name = edit_name.strip()
                            if name:
                                rename_book(book["id"], name)
                                st.session_state.editing_book_id = ""
                                st.session_state.editing_book_name = ""
                                if st.session_state.current_book_id == book["id"]:
                                    st.session_state.current_book = name
                                st.success("已更新")
                                _safe_rerun()
                            else:
                                st.warning("书籍名称不能为空")
                        if st.button(
                            "取消",
                            key=f"cancel_edit_{book['id']}",
                            use_container_width=True,
                        ):
                            st.session_state.editing_book_id = ""
                            st.session_state.editing_book_name = ""
                            _safe_rerun()
                    else:
                        if st.button(
                            "编辑", key=f"edit_{book['id']}", use_container_width=True
                        ):
                            st.session_state.editing_book_id = book["id"]
                            st.session_state.editing_book_name = book["name"]
                            _safe_rerun()

                with col_del:
                    if st.button(
                        "删除", key=f"del_{book['id']}", use_container_width=True
                    ):
                        st.session_state.delete_confirm_id = book["id"]
                        _safe_rerun()

                if st.session_state.delete_confirm_id == book["id"]:
                    st.warning(f"确定要删除《{book['name']}》吗？此操作不可恢复！")
                    col_confirm, col_cancel_del = st.columns(2)
                    with col_confirm:
                        if st.button(
                            "确认删除",
                            key=f"confirm_del_{book['id']}",
                            use_container_width=True,
                            type="primary",
                        ):
                            is_current_book = (
                                st.session_state.current_book_id == book["id"]
                            )
                            if is_current_book:
                                st.session_state.vectordb = None
                            delete_book_vector_store(book["id"])
                            delete_book(book["id"])
                            if is_current_book:
                                st.session_state.current_book_id = ""
                                st.session_state.current_book = ""
                                st.session_state.chat_history = []
                            if st.session_state.selected_book_id == book["id"]:
                                st.session_state.selected_book_id = ""
                            st.session_state.delete_confirm_id = ""
                            st.success("书籍已删除")
                            _safe_rerun()
                    with col_cancel_del:
                        if st.button(
                            "取消",
                            key=f"cancel_del_{book['id']}",
                            use_container_width=True,
                        ):
                            st.session_state.delete_confirm_id = ""
                            _safe_rerun()

        if total_pages > 1:
            _render_pagination(total_pages)

    st.markdown("---")
    if st.button("确定选择", use_container_width=True, type="primary"):
        if st.session_state.selected_book_id:
            select_book(st.session_state.selected_book_id)
            _safe_rerun()
        else:
            st.warning("请选择一本书")


def render_book_manager_dialog():
    """渲染书籍管理弹窗（使用Streamlit原生popover）"""
    pass


def render_bookshelf_sidebar():
    """渲染侧边栏的书籍管理区域"""
    st.header("文档管理")

    uploaded_file = st.file_uploader("上传文本文件到当前书籍", type="txt")

    if uploaded_file and st.button("追加上传"):
        if not st.session_state.current_book_id:
            st.warning("请先选择或创建一本书")
        else:
            uploaded_file.seek(0)
            raw = uploaded_file.read()
            name = getattr(uploaded_file, "name", "upload")

            if len(raw) == 0:
                st.error("文件为空，请选择有效的文本文件")
            elif len(raw) > 50 * 1024 * 1024:
                st.error("文件过大，建议不超过50MB")
            else:
                text = _decode_uploaded_text(raw)
                if text is None:
                    st.error("文件编码异常，请使用 UTF-8 / GBK / GB2312 格式")
                else:
                    logger.info(
                        "RAG upload (append): file=%r bytes=%s chars=%s",
                        name,
                        len(raw),
                        len(text),
                    )

                    with st.spinner("正在处理文件..."):
                        file_id = add_file_to_book(
                            st.session_state.current_book_id, name
                        )
                        vectordb, chunk_count = create_vector_store(
                            text,
                            st.session_state.current_book_id,
                            file_id,
                            name,
                            mode="append",
                        )

                        st.session_state.vectordb = vectordb
                        st.session_state.rag_content_hash = hashlib.sha256(
                            raw
                        ).hexdigest()

                        books = load_books_metadata()
                        book = get_book_by_id(st.session_state.current_book_id)
                        for f in book["files"]:
                            if f["id"] == file_id:
                                f["chunk_count"] = chunk_count
                                save_books_metadata(books)
                                break

                    st.success(
                        f"文件《{name}》已成功追加到《{st.session_state.current_book}》！"
                    )

    st.markdown("---")
    st.markdown("**当前书籍文件**")

    if st.session_state.current_book_id:
        book = get_book_by_id(st.session_state.current_book_id)
        if book and book.get("files"):
            for file in book["files"]:
                col_file, col_delete = st.columns([4, 1])
                with col_file:
                    st.markdown(f"📄 {file['name']}")
                with col_delete:
                    if st.button(
                        "✕",
                        key=f"btn_delete_file_{file['id']}",
                        use_container_width=True,
                    ):
                        delete_file_chunks(st.session_state.current_book_id, file["id"])
                        remove_file_from_book(
                            st.session_state.current_book_id, file["id"]
                        )
                        _safe_rerun()
        else:
            st.info("该书籍暂无文件")

    st.markdown("---")
    st.markdown("**书籍管理**")
    current_book_name = (
        st.session_state.current_book if st.session_state.current_book else "未选择书籍"
    )
    st.caption(f"当前书籍：{current_book_name}")

    with st.popover("书籍管理", use_container_width=True):
        _render_book_manager_content()

    st.markdown("---")
    if st.session_state.current_book_id:
        if not st.session_state.delete_current_book_confirm:
            if st.button("删除当前书籍"):
                st.session_state.delete_current_book_confirm = True
                _safe_rerun()
        else:
            st.warning(
                f"确定要删除《{st.session_state.current_book}》吗？此操作不可恢复！"
            )
            col_confirm, col_cancel = st.columns(2)
            with col_confirm:
                if st.button(
                    "确认删除",
                    key="confirm_delete_current",
                    use_container_width=True,
                    type="primary",
                ):
                    st.session_state.vectordb = None
                    delete_book_vector_store(st.session_state.current_book_id)
                    delete_book(st.session_state.current_book_id)
                    st.session_state.current_book_id = ""
                    st.session_state.current_book = ""
                    st.session_state.chat_history = []
                    st.session_state.delete_current_book_confirm = False
                    st.success("书籍已删除")
                    _safe_rerun()
            with col_cancel:
                if st.button(
                    "取消", key="cancel_delete_current", use_container_width=True
                ):
                    st.session_state.delete_current_book_confirm = False
                    _safe_rerun()

    st.markdown("---")
    if st.session_state.current_book_id:
        stats = get_vector_store_stats_for_book(st.session_state.current_book_id)
        book = get_book_by_id(st.session_state.current_book_id)
        st.info(f"文件数: {len(book.get('files', []))}")
        st.info(f"分块数: {stats['document_count']}")
    else:
        st.info("请选择或创建一本书")

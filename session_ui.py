"""Streamlit session controls; database is the source of conversation history."""
import streamlit as st
from utils import load_books_metadata
from book_manager import select_book


def restore_book(store):
    if st.session_state.get("session_restore_done"):
        return
    book_id = store.preference("last_book")
    if any(b["id"] == book_id for b in load_books_metadata()):
        select_book(book_id)
    st.session_state.session_restore_done = True


def render_sessions(store):
    book_id = st.session_state.current_book_id
    if not book_id:
        st.info("请选择书籍以管理会话")
        st.session_state.chat_history = []
        st.session_state.active_session_id = None
        return
    sessions = store.list(book_id)
    active = st.session_state.get("active_session_id")
    ids = [s["id"] for s in sessions]
    if active not in ids:
        active = store.active(book_id)
    if not active:
        active = store.create(book_id)
        sessions = store.list(book_id)
        ids = [s["id"] for s in sessions]
    names = {s["id"]: s["name"] for s in sessions}
    chosen = st.selectbox("会话", ids, index=ids.index(active), format_func=lambda sid: names[sid], key=f"session_picker:{book_id}:{active}")
    store.select(chosen, book_id)
    st.session_state.active_session_id = chosen
    st.session_state.chat_history = store.history(chosen, book_id)
    if st.button("新建会话", use_container_width=True):
        st.session_state.active_session_id = store.create(book_id)
        st.rerun()
    with st.form("rename_session:" + chosen):
        name = st.text_input("会话名称", value=names[chosen], max_chars=100)
        if st.form_submit_button("重命名"):
            store.rename(chosen, book_id, name)
            st.rerun()
    confirmed = st.checkbox("确认删除当前会话及全部问答", key="delete_session:" + chosen)
    if st.button("删除会话", disabled=not confirmed, use_container_width=True):
        store.delete(chosen, book_id)
        st.session_state.active_session_id = store.active(book_id)
        st.rerun()
    if st.button("清空当前会话历史", use_container_width=True):
        store.clear(chosen, book_id)
        st.session_state.chat_history = []
        st.rerun()

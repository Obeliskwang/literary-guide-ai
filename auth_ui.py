"""Restore browser login from HttpOnly cookie; keep model keys per login on server."""
import streamlit as st
from auth_service import AuthService, AuthError
from auth_api import COOKIE, start_server
from chat_backend import ChatSettings


@st.cache_resource
def auth_runtime():
    service = AuthService()
    service.initialize_demo_users()
    server = start_server(service)
    return service, server


def require_login():
    try:
        service, _ = auth_runtime()
    except OSError:
        st.error("鉴权服务启动失败，请确认 8000 端口未被占用。不要同时运行独立 auth_api.py。")
        st.stop()
    token = st.context.cookies.get(COOKIE, "")
    try:
        _, user = service.authenticated_session(token)
    except AuthError:
        st.title("伴读精灵 · 请先登录")
        st.link_button("打开登录页", "http://localhost:8000/login")
        st.caption("演示账号：demo / Demo@123456；请使用 localhost 打开应用。")
        st.stop()
    st.sidebar.caption(f"当前用户：{user['nickname']}（{user['role']}）")
    if st.sidebar.button("退出登录"):
        service.logout(token)
        st.session_state.clear()
        st.rerun()
    return service, token, user


def render_chat_settings(service, token, default_settings, local_model, embed_model):
    try:
        saved = service.get_model_settings(token)
    except (OSError, ValueError):
        st.error("本次登录的密钥无法解密，请退出后重新登录并填写。")
        st.stop()
    with st.sidebar.expander("回答模型", expanded=True):
        mode = st.radio("回答方式", ["远程 API", "本地 Ollama"], key="chat_mode")
        if mode == "本地 Ollama":
            model = st.text_input("本地模型 ID", value=local_model, key="local_chat_model")
            url = st.text_input("Ollama 网址", value="http://localhost:11434", key="local_chat_url")
            settings = ChatSettings("ollama", model, url)
        else:
            with st.form("user_ai_settings", clear_on_submit=True):
                model = st.text_input("远程模型 ID", value=saved.model if saved else default_settings.model)
                url = st.text_input("API 基础网址", value=saved.base_url if saved else default_settings.base_url)
                key = st.text_input("AI API 密钥", type="password", help="留空表示使用项目固定的模型、网址和密钥")
                submitted = st.form_submit_button("保存本次登录的配置")
            if submitted:
                if key.strip():
                    try:
                        service.save_model_settings(token, ChatSettings("api", model, url, key))
                    except (ValueError, OSError) as exc:
                        st.warning(str(exc))
                    else:
                        st.success("已保存，刷新页面仍有效；退出登录后清除。")
                else:
                    service.clear_model_settings(token)
                    st.info("使用项目固定的 AI 配置。")
                saved = service.get_model_settings(token)
            settings = saved or default_settings
            st.caption("当前使用：本次登录配置" if saved else "当前使用：项目固定配置")
            st.caption("密钥按本次登录加密保存，刷新及服务重启后仍有效；退出登录后清除。")
        st.caption(f"文档向量化固定使用本地 Ollama：{embed_model}")
    return settings

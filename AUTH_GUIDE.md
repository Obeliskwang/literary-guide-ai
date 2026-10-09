# 本地演示登录与模型配置

## 启动与测试账号

本机已有 bcrypt，无需新安装库。使用现有 Python：

```powershell
cd E:\Obeliskw\literary-ai-guide\literary-ai-guide-master
& "C:\Users\Lenovo\AppData\Local\Programs\Python\Python312\python.exe" -m streamlit run app.py
```

打开 http://localhost:8501，点击“打开登录页”，输入账号后自动返回应用。Streamlit 自动在 127.0.0.1:8000 启动鉴权服务，不要同时启动独立 auth_api.py。不要混用 localhost 和 127.0.0.1，浏览器 Cookie 按主机名隔离。

测试账号：

| username | password | nickname | role |
|---|---|---|---|
| demo | Demo@123456 | 演示用户 | user |
| admin | Admin@123456 | 演示管理员 | admin |

首次启动自动执行 auth_schema.sql 并初始化测试账号，重复启动不覆盖已有密码。也可执行 `python auth_service.py` 仅初始化数据库；`python auth_api.py` 仅启动独立 REST 演示服务。数据库位于 data/auth.sqlite3，包含 bcrypt 密码哈希、刷新令牌哈希和随机 JWT 签名密钥，不应提交版本控制。

## API

登录页使用原生 HTML/CSS/JavaScript，模板及素材在 `static/login/`。已按参考图采用左右双栏、左侧书页黄插画、右侧暖米白大圆角表单及暖灰棕外背景；窄屏自动改为上下布局。提供密码显示切换与提交状态提示。静态资源采用明确白名单路径提供，登录表单仍使用原有 CSRF 和 HttpOnly Cookie 流程。修改 Python 服务后需要重启 Streamlit；CSS/素材修改刷新登录页即可。

所有响应为 `{code, message, data}`；HTTP 状态与错误码一致，成功 HTTP 200 / code 0。

| 路由 | 请求 | data |
|---|---|---|
| POST /api/auth/login | JSON username、password | access_token、refresh_token、token_type、expires_in、user |
| GET /api/auth/me | Authorization: Bearer access_token | id、username、nickname、role |
| POST /api/auth/refresh | JSON refresh_token | access_token、token_type、expires_in |
| POST /api/auth/logout | JSON refresh_token | null |

JWT 使用 HS256，access_token 有效 2 小时；refresh_token 有效 7 天，每次登录独立生成，数据库只存 SHA256 哈希。刷新不延长刷新令牌的 7 天期限。退出撤销当前刷新令牌，也使该登录签发的 access_token 失效，其他登录不受影响。注销幂等。

错误码：0 成功、400 参数格式错误、401 凭证错误/过期/撤销、403 登录表单校验失败、404 接口不存在、500 服务错误。未提供原错误码表，因此采用此演示约定。错误用户名与错误密码均返回“用户名或密码错误”。

```powershell
$login = Invoke-RestMethod -Uri http://localhost:8000/api/auth/login -Method Post -ContentType application/json -Body '{"username":"demo","password":"Demo@123456"}'
Invoke-RestMethod -Uri http://localhost:8000/api/auth/me -Headers @{Authorization="Bearer " + $login.data.access_token}
Invoke-RestMethod -Uri http://localhost:8000/api/auth/refresh -Method Post -ContentType application/json -Body (@{refresh_token=$login.data.refresh_token} | ConvertTo-Json)
Invoke-RestMethod -Uri http://localhost:8000/api/auth/logout -Method Post -ContentType application/json -Body (@{refresh_token=$login.data.refresh_token} | ConvertTo-Json)
```

## 登录与用户模型密钥

登录页通过 HttpOnly、SameSite=Strict Cookie 保存 refresh_token，刷新浏览器仍可恢复登录。服务器每次运行页面验证其是否有效。Cookie 有效 7 天，与 refresh_token 一致；退出时服务端撤销令牌，旧 Cookie 即使仍存在也无效，新登录会覆盖它。

回答默认使用 config.py 中 AI_MODEL_NAME、AI_BASE_URL、AI_API_KEY，配置需填写真实可用值。用户可以在侧边栏填写自己的模型 ID、基础网址和 AI API 密钥并点击保存。自定义 Key 不回显，使用 Windows 系统自带 DPAPI 加密后按本次登录存入 login_model_settings，刷新和服务重启后仍有效；退出时删除密文并清空内存缓存。重复登录不会继承其他登录的自定义 Key。输入空 Key 并保存会恢复整套项目默认配置，避免把项目密钥发给自定义网址。登录到期后的配置在访问时或下次启动清理。

密钥解密绑定当前 Windows 用户；将数据库复制到其他电脑/Windows 用户后无法解密。本模块针对当前 Windows 演示环境，无新增加密库；跨平台迁移需要另行选择密钥管理方案。

本地 Ollama 回答方式仍可选择，文档上传与检索始终使用本地 bge-m3，不使用用户填写的远程密钥。

## 演示边界

仅绑定本机，HTTP Cookie 不设置 Secure（localhost 演示）；不是生产部署。role 作为基本信息返回，尚未设计按角色限制功能。现有书架、向量库及聊天数据库为共享演示数据，本模块提供登录门禁和凭证隔离，不提供多用户数据隔离。无注册、改密、找回密码及防爆破策略。

测试：`python -m unittest discover -s tests -p "test_auth*.py" -v`。

2026-10-06 验证：14 项测试通过，覆盖真实本机 HTTP 接口、SQLite、bcrypt、JWT 到期/篡改/撤销、重复登录、DPAPI 加密与重启恢复，以及 Streamlit 官方 AppTest 的刷新状态恢复、默认配置回退、退出清除和完整应用登录门禁。未调用真实模型 API。

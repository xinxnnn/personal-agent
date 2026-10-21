# 智契化身

本仓库包含用户端、信任提供方（TP）审核端、智能体提供方（AP）管理端，以及 Octopus / OpenClaw 智能体相关代码。下面的步骤以 **Windows 本机演示** 为准；三个网页由 Python 服务直接提供，不需要单独启动前端开发服务器。

## 1. 启动三个网页

下载仓库并解压，在项目根目录打开三个 PowerShell 终端，依次运行以下命令（每个终端一条；首次运行请等第一条完成依赖安装后再运行后两条）：

```powershell
.\start_ap_8112.bat
.\start_tp_8111.bat
.\start_user_8110.bat
```

脚本会分别启动 AP 管理端、TP 审核端和用户端，并在默认浏览器打开对应网页。首次运行会自动创建 `.venv312`、安装网页服务所需依赖，因此需要联网，启动可能较慢。服务启动后在后台运行；运行 `.\stop_all.bat` 可停止由这些脚本启动的服务及其子进程。由于服务在后台独立运行，启动窗口中的 `Ctrl+C` 或关闭编辑器不会自动停止服务；退出项目或移动/重命名项目目录前，请先运行 `.\stop_all.bat`。

脚本会寻找 Python 3.11 或 3.12；若没有 Python 但电脑有 Windows 包管理器 `winget`，会尝试自动安装 Python 3.12。没有 Python 且没有 winget，或电脑无法联网时，首次运行需先手动安装 Python 3.12 并连网安装依赖。仓库不包含虚拟环境。只有启动 OpenClaw 执行分支时才需要额外准备 Node.js、npm 和 Git；运行 Octopus 实例会在首次启动时为实例安装其 Python 依赖。

运行日志位于 `local_store/bootstrap_logs/`。脚本不会强制结束占用端口的其他程序；如果端口冲突，会给出错误信息。

## 2. 本机网址

| 页面 | 本机地址 | 演示账号 |
| --- | --- | --- |
| 用户端 | <http://127.0.0.1:8110/user> | `user` / `pa@2026` |
| 用户端简版工作台 | <http://127.0.0.1:8110/user/static/experience/index.html> | 同上 |
| TP 申领与删除审核端 | <http://127.0.0.1:8111/tp> | `tpadmin` / `pa@2026` |
| AP 管理端 | <http://127.0.0.1:8112/ap> | `apadmin` / `pa@2026` |

未登录时会跳转到各自的 `/login` 页面。用户端的“连接与设置”应指向 `http://127.0.0.1:8111` 和 `http://127.0.0.1:8112`。`/user` 使用在线 CDN 加载 Vue 和 Element Plus；若浏览器无法连接 CDN，页面会显示提示并提供本地简版工作台入口。简版工作台的页面脚本和样式位于仓库内，不依赖 CDN。

首次启动时，项目会在被 Git 忽略的 `local_store/crypto_keys.json` 中生成并保存一套本机密钥，供 TP、AP 和用户服务共享；该文件是私密运行数据，切勿提交或分享。重置项目数据时删除该文件会生成新的密钥，旧凭证将无法再由新密钥验证。

## 3. 完成申领流程前，还需配置什么

**登录和浏览页面**不需要先申请身份，也不需要 ANP 网关；但**真实提交身份申领**需要可连接的 MySQL，以及表中与申请人对应的照片记录。TP 当前读取环境变量 `MYSQL_HOST`、`MYSQL_PORT`、`MYSQL_USER`、`MYSQL_PASSWORD`、`MYSQL_DB`、`MYSQL_TABLE`；代码默认分别是 `127.0.0.1`、`3306`、`root`、`1234`、`avatar`、`bi`。请在启动 TP 的 PowerShell 窗口中先设置你自己的值，例如：

```powershell
$env:MYSQL_HOST='127.0.0.1'
$env:MYSQL_PORT='3306'
$env:MYSQL_USER='你的数据库用户'
$env:MYSQL_PASSWORD='你的数据库密码'
$env:MYSQL_DB='avatar'
$env:MYSQL_TABLE='bi'
.\start_tp_8111.bat
```

TP 会按申请中的身份编号查询 `bi.user_id`，并将 `bi.pic_string` 与本次上传照片的数据比较。库中没有该用户、照片数据不一致或数据库不可用时，页面虽能打开，身份核验仍无法通过。演示账号只用于**登录网页**，不代表数据库已准备好，也不保证申领自动通过。通过用户端提交后，在 TP 页面审核申请，再返回用户端查看审批结果。

创建并运行智能体还需要可用的模型服务。本仓库按项目维护者要求包含 `agent_provider/octopus/.env` 与 `agent_provider/openclaw/.env` 中的现有模型配置；如这些密钥失效或不适用于你的环境，可在对应文件中填写自己的 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和模型名称。Octopus 的字段可参考 `agent_provider/octopus/.env_template`，OpenClaw 可参考 `agent_provider/openclaw/.env.example`。也可以在实例生成后，通过页面的模型配置入口为该实例单独设置。仅启动三个网页不等于模型对话已经可用。

## 4. 常见问题与运行边界

- `.venv312\Scripts\python.exe` 不存在：三个启动脚本会自动创建；如果失败，检查 Python/winget 与网络连接。
- 提示 `No module named pip`：运行 `.\.venv312\Scripts\python.exe -m ensurepip --upgrade` 修复虚拟环境中的 pip；启动脚本也会在安装服务依赖前自动尝试此修复。
- 端口 8110、8111、8112 被占用：启动脚本不会结束其他进程，请先关闭冲突程序。
- 申领时报 `db_check_failed` 或照片核验失败：检查 TP 终端的 MySQL 环境变量、数据库连接及 `bi` 表中的 `user_id`/`pic_string`。
- 智能体聊天失败：查看实例运行日志与模型地址、密钥、模型名称；网页显示 Ready 只代表实例服务已启动。
- ANP：Octopus 组内通信会由用户服务自动管理本机网关，不需要手动启动单独的网关进程；但部署 Octopus 组通信仍需要项目根目录中的 `anp-proxy/` 源码。启动脚本检测到该目录后会自动按 `requirements-anp.txt` 安装依赖。若部署时报 `ANP 网关未启动`，先检查 `local_store/anp-gateway.log`；若显示 `No module named 'anp_proxy'`，确认 `anp-proxy/` 已完整放在项目根目录，然后运行 `.\.venv312\Scripts\python.exe -m pip install -r requirements-anp.txt` 并重启服务。若下载包中没有 `anp-proxy/`，需要先从项目原始发布包补齐该目录；该依赖清单使用本地 editable 路径，不能在源码缺失时单独安装。Octopus 界面选择“ANP 通信”并选择同组在线伙伴后，目标智能体会自动调用自己的模型回答；来信、生成中的状态及回复会同步显示在双方界面，并保存在各自本地会话记录中。更新项目代码后，应在用户工作台停止并重新启动两个 Octopus 实例，让新版本聊天页和接口同步到已生成的实例包，再刷新两边的聊天页面。首次身份认证及目标模型服务必须可用。
- 协同工作日志：用户简版工作台的日志按时间记录智能体启动/停止、Agent 间请求发出/收到、结果返回/接收及失败事件；只记录事件元数据，不保存或展示问答正文，也不显示事件统计数字。

这些演示脚本只监听本机地址，使用演示账号和固定测试密钥。不要直接把它们作为公网部署配置。`local_store/`、`data/`、身份私钥和日志属于本机数据，不在 GitHub 下载包中；上述两个模型 `.env` 则包含在仓库中。

## 本次运行核验

2026-10-17 除已有环境外，还从空虚拟环境实际运行了 `scripts/start_local.ps1`：脚本创建虚拟环境、在线安装依赖，并启动 TP、AP 和用户服务；三个新服务逐一通过了演示账号登录、受保护主页加载和静态资源请求。身份申领、MySQL 照片比对、外部模型对话与首次安装智能体依赖需要外部服务或数据，本次未作端到端验证。

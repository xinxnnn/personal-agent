# 信锚 Agent-Anchor：Octopus 行为图谱认证

本功能保护工作台的 ANP 消息收发链路 `/local-anp/send` → `/local-anp/receive`，
以及 Octopus 内置页面的 `/v1/chat/anp` → `/local-anp/chat` 对话链路。
内置页面切换到“ANP 通信”，填写目标主机 Host:Port，或从刷新后的同组地址提示中选择伙伴，
即可先认证、再调用目标模型并接收回复。地址提示失败不禁用手动输入。
保留原有可选网关输入；信锚管理的同组实例使用系统管理网关，独立启动的原版 ANP 流程仍使用用户配置。
侧栏显示首次密钥认证或历史挑战认证结果，以及本地可信事件数量。
目标回复的摘要也包含在接收方签名事件中，发送方验证后才展示成功结果。
首次双向交互后，停止并重新启动两个实例，再次发送新消息，即可看到“历史挑战认证通过”。
认证在每条新消息上执行，因此 WebSocket 断线恢复也不会复用旧的认证许可。
重复消息若已有回执则返回原回执，不代表执行了新一轮认证。

## 代码入口

- `app/identity_memory.py`：Ed25519 密钥、签名事件、SQLite 语义图谱、挑战及响应验证。
- `app/group_anp.py:prepare`：受信管理进程为实例登记公钥，密钥变更时拒绝自动替换。
- `app/octopus_group_runtime.py:attach`：挑战接口、消息发送前应答、接收前认证、双边保存签名证据。
- `app/web_user/experience/anp.js`：显示可信事件数量及最近一次接收认证模式。
- `tests/test_identity_memory.py`：真实 ANP 网关断开重连与认证安全测试。
- `tests/test_octopus_anp.py`：原生 Octopus 运行及鉴权回归测试，增加受信公钥配置。
- `agent_provider/octopus/pyproject.toml`：显式声明 cryptography 依赖。

## 知识图谱实际在哪里参与

每个实例独立保存 `local_store/agents/<id>/identity_memory.sqlite3`。

`record()` 验证发送方对请求的签名，以及接收方对接收事件的签名，然后写入：

- `events`：双方签名的原始证据，仅保存消息内容摘要，不保存消息明文。
- `nodes`：身份、动作、时间、内容摘要、组作用域等有类型的语义节点。
- `edges`：事件与发送方、接收方、动作、时间、对象、作用域之间的关系。

例如，一条事件关联“发送方 A”“接收方 B”“动作 message.received”“内容摘要 H”。
所有边保留事件编号，不能把两个事件的属性拼成不存在的事件。

`query()` 对发送方、接收方、动作三种关系执行 SQL 图关系交集查询，并重新验证查询出的签名证据。
`challenge()` 在验证方自己的图谱里选择历史事件，挑战只给出事件编号，不发送预期证据摘要。
`answer()` 在发送方自己的图谱检索该事件，将本地证据摘要与挑战一起签名。
`authenticate()` 对照验证方独立保留的证据，校验签名、内容一致性及一次性挑战。

这是一种 SQLite 实现的语义关系图，不是向量相似度检索，也不由大模型判断身份。
当前固定模式是论文行为记忆图谱思路的最小工程实现，不是完整论文协议的复现。

## 协议与状态

1. 先通过已有组成员校验与本机令牌检查。
2. 接收方签发挑战：随机 nonce、组作用域、双方实例 ID、请求摘要、60 秒有效期、历史事件 ID。
3. 首次没有历史时使用 `bootstrap`：验证受信注册密钥的持有证明，不宣称行为认证已通过。
4. 有历史时使用 `history`：响应必须包含签名正确且一致的本地历史证据摘要。
5. SQLite `BEGIN IMMEDIATE` 保证挑战只能消费一次，防止并发重放。
6. 接收方确认消息后签署事件；双方各自验证并保存，供后续挑战使用。

`challenges` 保存短期挑战，`audit` 保存成功认证的模式、对端、事件编号与时间。
原有 `anp_messages.sqlite3` 继续承担用户收发件箱。旧消息不自动转为可信历史。
原有实例首次使用新功能时，应重启用户服务及通信双方，让管理服务登记公钥。

## 安全与范围

- 信任根是本机管理服务维护的实例 ID—公钥注册，不是新增 PHC/PA 签名验证。
- 实例私钥在 `identity_memory.key`，应受运行账户文件权限保护。Windows 下 chmod 不等价于独立 ACL 隔离。
- 当前同机实例并未实现操作系统级互相隔离；能读取双方私钥、修改注册表和图谱的攻击者不在此保证范围内。
- 同时复制私钥和完整历史的攻击者不能靠这一机制区分。
- `/local-anp/chat` 现在强制校验一次性身份挑战，通过后才能调用模型。PHC 首次申领、凭证撤销机制和 OpenClaw 不变。
- 历史不足、签名错误、证据丢失或图关系损坏不会标记为“历史认证通过”。单边丢失历史会阻止继续认证，需要可信管理流程核对与修复，不能自动降级。
- 如果对方已保存接收证据，但发送方在保存回执前中断，可能出现上述单边缺失；自动证据同步恢复不在此最小版本内。
- 认证通过只允许这次消息投递，不授予额外工具权限，不表示模型已执行任务。

## 验证

```powershell
.\.venv312\Scripts\python.exe -m unittest discover -s tests -p test_identity_memory.py
.\.venv312\Scripts\python.exe -m unittest discover -s tests -p test_octopus_anp.py
.\.venv312\Scripts\python.exe -m unittest discover -s tests -p test_native_anp_identity.py
```

测试使用临时实例、真实本机 ANP 网关和 WebSocket。行为认证测试不调用模型、不发送用户现有消息。
内置对话测试使用可记录调用次数的模型替身，检查无认证请求不能触发模型；不验证真实模型供应商连通性。

已有实例的页面/API 可运行 `scripts/sync_octopus_anp_ui.py` 同步；脚本仅覆盖指定页面、脚本、聊天路由及认证中间件文件并先保存备份，
不覆盖 `.env`、凭证、密钥或行为图谱。同步后需重启对应 Octopus 实例并强制刷新页面。

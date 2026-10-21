# Agent Provider (AP) 详细开发指南

## 一、概述

**Agent Provider (AP)** 服务是 **Octopus 多智能体生态** 的核心基础设施，它扮演着 "智能体工厂" 和 "信任锚点" 的双重角色。AP 不仅负责维护和分发智能体的核心代码（Octopus），还负责通过严格的密码学协议签发和管理 Personal Agent (PA) 凭证。

本指南将 AP 分为两个逻辑层面进行详细阐述：
1.  **管理平面 (`ap.py`)**：作为一个权威服务，处理凭证签发、CMM 协商、加密绑定和生命周期管理。
2.  **数据平面 (`octopus/`)**：作为源代码模板，定义了智能体的运行架构、业务逻辑、插件扩展方式和通信协议。

---

## 二、第一部分：AP 服务框架 (`ap.py`)

AP 服务是一个基于 FastAPI 的独立应用，区别于智能体本身，它更像是一个 "发证局"。

### 1. 核心技术实现

AP 服务的核心在于维护 PHC (Personhood Credential) 与 PA (Personal Agent) 之间的强绑定关系，确保智能体 "人机合一"。

*   **传输安全**：所有与 User 端的交互均通过 **ElGamal** 算法进行加密传输，确保 payload 只有持有私钥的一方可解密。
*   **身份验证**：使用 **Schnorr** 签名算法验证 User 和 TP 的签名，并对签发的 PA 进行签名。
*   **绑定机制**：
    *   **AF (Anchoring Factor)**：锚定因子，将 PA 绑定到特定的物理设备 (HID)。
    *   **CMI (Computation Module Identifier)**：计算模块标识符，确保运行的代码未被篡改。
    *   **CH/CCH (Configuration Hash)**：配置哈希，锁定智能体的能力清单。

### 2. 关键 API 详解

#### (1) `/ap/request_pa` (PA 签发)
*   **描述**：基于用户的 PHC 签发对应的 PA 凭证。
*   **输入**：加密的 `PHC` 和 `HID`。
*   **处理逻辑**：
    1.  解密请求，验证 PHC 格式。
    2.  生成 `APM` (AP Metadata)，包含当前时间戳和 CMI。
    3.  使用 AP 私钥对 `APM` 进行 Schnorr 签名，生成 `APA` (AP Attestation)。
    4.  生成随机数 `r_bind2` 用于后续的密码学混淆。
*   **输出**：加密的 `PA` 对象（包含 APM 和 APA）。

#### (2) `/ap/cmm_init` (CMM 协商初始化)
*   **描述**：用户请求构建智能体时，首先获取可选的计算模块清单。
*   **输入**：`PHC`, `HID`, `TPAC`。
*   **处理逻辑**：
    1.  验证 PHC 中的 TP 签名，确保证书合法。
    2.  根据系统策略，生成一份 `CMM` (Computation Module Manifest) 模板。
    3.  模板包含：输入模块（文本/语音）、处理模块（RAG/逻辑）、输出模块（TTS/渲染）等。
*   **输出**：加密的 CMM 模板。

#### (3) `/ap/cmm_submit` (CMM 提交与绑定)
*   **描述**：用户选定模块后，提交清单，AP 完成最终绑定。
*   **输入**：`CMC` (选定的配置), `CMI_code` (本地代码哈希), `PHC`。
*   **处理逻辑**：
    1.  **计算 CMI**：基于用户提交的 CMC 计算模块哈希。
    2.  **验证 AF**：重算锚定因子，必须与 PHC 中的 AF 一致，证明是同一设备。
    3.  **计算 CH/CCH**：生成配置哈希，锁定该智能体的能力范围。
    4.  **持久化**：将 `HID` -> `CMI/CMC` 的映射写入本地数据库，用于恢复。
*   **输出**：最终的 `PA` 凭证，以及用于更新 User 端 PHC 的证明数据。

### 3. 数据存储结构 (`local_store/ap_db/`)

AP 使用本地文件系统作为轻量级数据库，每个 HID 对应一个 JSON 文件：

```json
// 文件名: <HID>.json
{
  "CMC": [...],          // 用户的模块配置清单
  "CMI": "12345...",     // 计算出的模块标识符
  "r_bind2": "9876...",  // 绑定随机数
  "ts": "2024-01-01..."  // 创建时间
}
```

---

## 三、第二部分：Octopus 核心 (`octopus/`)

这部分代码是 **PA 的灵魂**。当 User 端拿到 AP 签发的 PA 凭证后，会使用这份代码在本地启动智能体实例。

### 1. 目录结构深度解析

```
octopus/
├── agents/                 # [业务层] 智能体具体实现
│   ├── base_agent.py       # 基类，定义了生命周期和通用接口
│   ├── personal_agent.py   # 个性化智能体，处理用户偏好
│   └── message/            # 消息处理模块
├── router/                 # [调度层] 任务分发中心
│   ├── agents_router.py    # 基于语义/规则的路由器
│   └── rpc_services.py     # JSON-RPC 接口实现
├── core/                   # [通信层] 核心底层设施
│   ├── receiver/           # ANP 协议接收器
│   └── protocol/           # 协议编解码 (Chunking, Encryption)
├── anp_sdk/                # [SDK层] 跨智能体通信工具包
│   ├── anp_client.py       # 发送 ANP 请求的客户端
│   └── anp_auth/           # DID-WBA 鉴权模块
├── api/                    # [接口层] 对外 HTTP 接口
│   └── chat_router.py      # OpenAI 兼容的聊天接口
└── master_agent.py         # [控制层] 主智能体，协调全局
```

### 2. 智能体开发进阶

#### (1) 完整的智能体定义
一个成熟的智能体通常包含初始化逻辑、依赖注入和多个能力方法。

```python
from octopus.agents.base_agent import BaseAgent
from octopus.router.agents_router import register_agent, agent_method
import aiohttp

@register_agent(
    name="crypto_price_agent",
    description="加密货币价格查询助手",
    version="1.0.0",
    dependencies=["aiohttp"] # 声明依赖
)
class CryptoPriceAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.api_url = "https://api.coingecko.com/api/v3"

    async def initialize(self):
        """生命周期钩子：在智能体启动时调用"""
        self.session = aiohttp.ClientSession()
        self.logger.info("CryptoPriceAgent initialized")

    async def cleanup(self):
        """生命周期钩子：在智能体关闭时调用"""
        await self.session.close()

    @agent_method(
        description="获取指定代币的当前价格",
        parameters={
            "token_id": {"type": "string", "description": "代币ID，如 bitcoin"},
            "currency": {"type": "string", "description": "计价货币，默认 usd"}
        },
        returns="dict"
    )
    async def get_price(self, token_id: str, currency: str = "usd") -> dict:
        try:
            url = f"{self.api_url}/simple/price?ids={token_id}&vs_currencies={currency}"
            async with self.session.get(url) as resp:
                data = await resp.json()
                return {
                    "token": token_id,
                    "price": data[token_id][currency],
                    "currency": currency.upper()
                }
        except Exception as e:
            self.logger.error(f"Error fetching price: {e}")
            return {"error": str(e)}
```

#### (2) 智能体间的通信
Octopus 支持智能体之间相互调用，即使它们不在同一个进程中。

```python
# 在 Agent A 中调用 Agent B
target_agent = "text_processor"
method = "summarize"
params = {"text": long_content}

# 通过 Router 本地调用（如果 B 也在本地）
result = await self.router.call_agent(target_agent, method, **params)

# 或者通过 Master Agent 自动调度
result = await self.master.process_task("请帮我总结这段文本...", context={})
```

### 3. ANP 通信机制

**Agent Network Protocol (ANP)** 是 Octopus 的神经网络。

*   **寻址**：每个智能体由 `DID` (Decentralized Identifier) 唯一标识。
*   **发现**：通过 `ANP Gateway` 或本地广播发现其他智能体。
*   **鉴权**：使用 **DID-WBA** (Web-Based Authentication) 进行握手，无需共享密钥。
*   **传输**：支持大文件分片 (Chunking) 和断点续传，所有数据端到端加密。

---

## 四、总结

Agent Provider 是连接 "用户身份" 与 "智能体能力" 的桥梁。

1.  **对于系统开发者**：主要关注 `octopus/` 目录，通过扩展 `agents/` 和优化 `core/` 来增强智能体的能力上限。
2.  **对于平台运营者**：主要关注 `ap.py`，通过管理密钥、配置 CMM 模板和监控发证日志，来确保整个生态的安全与可控。

通过遵循本指南，您可以构建出既安全可信，又具备强大扩展能力的个性化智能体系统。

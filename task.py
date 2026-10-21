from typing import Any
import asyncio

# Mocks to suppress IDE errors
def extract_auth_header_parts(x): return [""] * 5
class DidWbaVerifierError(Exception):
    def __init__(self, msg, status_code=400): pass
async def resolve_did_wba_document(x): return {}
def verify_auth_header_signature(**kwargs): return True, ""
class MockLogger:
    def warning(self, *args, **kwargs): pass
logger = MockLogger()

# did_wba_verifier.py

async def _handle_did_auth(self, authorization: str, domain: str) -> dict[str, Any]:
    # 1. 解析 Authorization 头 (包含 DID, Nonce, 时间戳, 签名)
    header_parts = extract_auth_header_parts(authorization)
    did, nonce, timestamp, verification_method, signature = header_parts

    # 2. 校验时间戳 (防止过期请求)
    if not self._verify_timestamp(timestamp):
        raise DidWbaVerifierError("Timestamp expired", status_code=401)

    # 3. 校验 Nonce (防止重放攻击)
    if not await self._is_valid_server_nonce(did, nonce):
        raise DidWbaVerifierError("Invalid or expired nonce", status_code=401)

    # 4. 解析 DID 文档 (获取公钥)
    did_document = await resolve_did_wba_document(did)

    # 5. 验证数字签名 (确保请求由私钥持有者发起)
    is_valid, message = verify_auth_header_signature(
        auth_header=authorization,
        did_document=did_document,
        service_domain=domain,
    )
    if not is_valid:
        raise DidWbaVerifierError(f"Invalid signature: {message}", status_code=401)

    return {"did": did}



    # websocket_manager.py

async def _cleanup_loop(self) -> None:
    """定期清理失效连接 (Zombie Connections)"""
    while True:
        try:
            await asyncio.sleep(60)  # 每 60 秒执行一次检查

            current_time = asyncio.get_event_loop().time()
            stale_connections = []

            for conn_id, conn_info in self.connections.items():
                # 如果当前时间 - 上次 Ping 时间 > 2 倍心跳间隔，判定为掉线
                if current_time - conn_info.last_ping > self.config.ping_interval * 2:
                    stale_connections.append(conn_id)

            # 强制关闭所有判定为失效的连接
            for conn_id in stale_connections:
                conn_info = self.connections.get(conn_id)
                if conn_info:
                    logger.warning("Closing stale connection", connection_id=conn_id)
                    await conn_info.websocket.close()

        except asyncio.CancelledError:
            break

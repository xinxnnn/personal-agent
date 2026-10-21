"""Loopback-only gateway using the repository's ANPX transport."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'anp-proxy'))
from anp_proxy.common.config import GatewayConfig, AuthConfig
from anp_proxy.gateway.server import GatewayServer

async def main():
    gateway=GatewayServer(GatewayConfig(host='127.0.0.1',port=int(sys.argv[1]),
        wss_host='127.0.0.1',wss_port=int(sys.argv[2]),auth=AuthConfig(enabled=False,did_wba_enabled=False)))
    await gateway.start()
    try: await asyncio.Event().wait()
    finally: await gateway.stop()

if __name__=='__main__': asyncio.run(main())

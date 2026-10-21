"""ANP Proxy library entry point and CLI."""
import asyncio
import sys
from pathlib import Path
import click

from .common.config import ANPConfig
from .common.log_base import get_logger, setup_logging
from .gateway import GatewayServer
from .receiver import ReceiverClient

logger = get_logger(__name__)


class ANPProxy:
    """ANP Proxy library interface."""

    def __init__(self, config: ANPConfig) -> None:
        """
        Initialize ANP Proxy.

        Args:
            config: ANP configuration
        """
        self.config = config

        # Setup logging
        setup_logging(config.logging)

        logger.info("ANP Proxy library initialized", mode=config.mode)

    def create_gateway_server(self) -> GatewayServer:
        """Create Gateway server instance."""
        return GatewayServer(self.config.gateway)

    def create_receiver_client(self, app=None) -> ReceiverClient:
        """Create Receiver client instance."""
        return ReceiverClient(self.config.receiver, app)


# For backwards compatibility
@click.command()
@click.option("--config", "-c", type=click.Path(exists=True), help="Configuration file path")
@click.option("--mode", "-m", type=click.Choice(["gateway", "receiver", "both"]), help="Operating mode")
@click.option("--gateway-host", help="Gateway HTTP host")
@click.option("--gateway-port", type=int, help="Gateway HTTP port")
@click.option("--wss-host", help="WebSocket server host")
@click.option("--wss-port", type=int, help="WebSocket server port")
@click.option("--gateway-url", help="Gateway WebSocket URL for receiver")
@click.option("--local-app", help="Local ASGI app module (e.g., 'myapp:app')")
@click.option("--log-level", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]), help="Log level")
@click.option("--debug", is_flag=True, help="Enable debug mode")
def main(
    config: str | None = None,
    mode: str | None = None,
    gateway_host: str | None = None,
    gateway_port: int | None = None,
    wss_host: str | None = None,
    wss_port: int | None = None,
    gateway_url: str | None = None,
    local_app: str | None = None,
    log_level: str | None = None,
    debug: bool = False,
) -> None:
    try:
        anp_config = ANPConfig.from_file(Path(config)) if config else ANPConfig()

        if mode:
            anp_config.mode = mode
        if gateway_host:
            anp_config.gateway.host = gateway_host
        if gateway_port:
            anp_config.gateway.port = gateway_port
        if wss_host:
            anp_config.gateway.wss_host = wss_host
        if wss_port:
            anp_config.gateway.wss_port = wss_port
        if gateway_url:
            anp_config.receiver.gateway_url = gateway_url
        if local_app:
            anp_config.receiver.local_app_module = local_app
        if log_level:
            anp_config.logging.level = log_level
        if debug:
            anp_config.debug = True
            anp_config.logging.level = "DEBUG"

        setup_logging(anp_config.logging)

        async def run_gateway():
            server = GatewayServer(anp_config.gateway)
            await server.run()

        async def run_receiver():
            client = ReceiverClient(anp_config.receiver)
            await client.run()

        async def run_both():
            server = GatewayServer(anp_config.gateway)
            client = ReceiverClient(anp_config.receiver)
            await asyncio.gather(server.run(), client.run())

        if sys.platform == "win32":
            if anp_config.mode == "gateway":
                asyncio.run(run_gateway())
            elif anp_config.mode == "receiver":
                asyncio.run(run_receiver())
            elif anp_config.mode == "both":
                asyncio.run(run_both())
            else:
                raise ValueError(f"Invalid mode: {anp_config.mode}")
        else:
            try:
                import uvloop
                uvloop.install()
            except Exception:
                pass
            if anp_config.mode == "gateway":
                asyncio.run(run_gateway())
            elif anp_config.mode == "receiver":
                asyncio.run(run_receiver())
            elif anp_config.mode == "both":
                asyncio.run(run_both())
            else:
                raise ValueError(f"Invalid mode: {anp_config.mode}")
    except KeyboardInterrupt:
        print("Received interrupt signal, shutting down")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


__all__ = ["ANPProxy", "ANPConfig", "GatewayServer", "ReceiverClient"]

import asyncio
import logging
from typing import AsyncGenerator, Callable, Optional
import httpx
from config import config
from logger import logger

class SSETransport:
    """Manages the persistent HTTP/SSE connection to the AGP MCP server."""
    
    def __init__(self, server_url: str, token: str):
        self.server_url = server_url
        self.token = token
        self.client: Optional[httpx.AsyncClient] = None
        self.post_url: Optional[str] = None
        self.endpoint_received = asyncio.Event()
        self.incoming_queue: asyncio.Queue = asyncio.Queue()
        self.is_connected = False
        self.read_task: Optional[asyncio.Task] = None
        self.on_disconnect: Optional[Callable[[], None]] = None
        self.on_reconnect: Optional[Callable[[], None]] = None

    async def connect(self) -> None:
        """Establishes the SSE connection and starts reading events."""
        if self.is_connected:
            return

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "text/event-stream"
        }
        
        # Configure connection pool and client
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        self.client = httpx.AsyncClient(headers=headers, limits=limits, timeout=60.0)
        
        logger.info(f"[cyan]🏁 [PHASE 1/3] Establishing Telemetry Connection to Grid...[/cyan]")
        
        try:
            # We open an event stream via GET request
            # We use an exit stack or enter the context manually to keep the stream open
            self.is_connected = True
            self.endpoint_received.clear()
            self.read_task = asyncio.create_task(self._read_stream_loop())
        except Exception as e:
            self.is_connected = False
            logger.error(f"[red]Failed to connect to SSE stream: {e}[/red]")
            await self.close()
            raise

    async def _read_stream_loop(self) -> None:
        """Asynchronous background loop to read events from the SSE stream."""
        backoff = 1.0
        max_backoff = 32.0
        
        while self.is_connected:
            try:
                headers = {
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "text/event-stream"
                }
                async with self.client.stream("GET", self.server_url, headers=headers) as response:
                    if response.status_code != 200:
                         raise httpx.HTTPStatusError(
                            f"SSE connect failed with status code {response.status_code}",
                            request=response.request,
                            response=response
                        )
                    
                    # Connection established, reset backoff
                    backoff = 1.0
                    logger.info("[green]🟢 [PHASE 1/3] Telemetry Connected! (SSE Link Online)[/green]")
                    
                    buffer = ""
                    async for chunk in response.aiter_text():
                        # Append normalized chunk to buffer
                        # This handles CRLF sequences split across TCP chunk boundaries
                        buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")
                        while "\n\n" in buffer:
                            event_block, buffer = buffer.split("\n\n", 1)
                            await self._parse_event_block(event_block)
                            
            except (httpx.HTTPError, httpx.StreamError, Exception) as e:
                if not self.is_connected:
                    break
                logger.error(f"[red]SSE transport read error: {e}. Reconnecting in {backoff:.1f}s...[/red]")
                self.endpoint_received.clear()
                if self.on_disconnect:
                    try:
                        self.on_disconnect()
                    except Exception as callback_err:
                        logger.error(f"Error in disconnect callback: {callback_err}")
                
                await asyncio.sleep(backoff)
                # Exponential backoff with jitter
                backoff = min(backoff * 2.0, max_backoff)

    async def _parse_event_block(self, block: str) -> None:
        """Parses an SSE block into events and queues JSON-RPC messages."""
        lines = block.strip().split("\n")
        event_type = "message"
        data_lines = []

        for line in lines:
            if not line:
                continue
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip()
                val = val.lstrip()
                if key == "event":
                    event_type = val
                elif key == "data":
                    data_lines.append(val)

        event_data = "\n".join(data_lines) if data_lines else ""

        if not event_data:
            return

        if event_type == "endpoint":
            # The 'endpoint' event contains the URI where the client sends POST messages
            self.post_url = event_data
            self.endpoint_received.set()
            logger.info(f"[green]🟢 [PHASE 2/3] Telemetry Router Configured! (POST Route Set)[/green]")
            if self.on_reconnect:
                try:
                    self.on_reconnect()
                except Exception as reconnect_err:
                    logger.error(f"Error in reconnect callback: {reconnect_err}")
        elif event_type == "message":
            # Event type 'message' contains a JSON-RPC payload
            await self.incoming_queue.put(event_data)

    async def send_post(self, payload: str) -> httpx.Response:
        """Sends a JSON-RPC message via HTTP POST to the established post_url."""
        if not self.post_url:
            logger.info("[yellow]POST endpoint not received yet. Waiting for SSE connection...[/yellow]")
            try:
                await asyncio.wait_for(self.endpoint_received.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                raise ConnectionError("Cannot send message. SSE 'endpoint' event was not received after 30s.")

        if not self.client:
            raise ConnectionError("Transport client is not initialized.")

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        
        # Resolve relative URL if necessary
        url = self.post_url
        if not url.startswith("http"):
            # If server sends a relative path, join it with the base domain of server_url
            from urllib.parse import urljoin
            url = urljoin(self.server_url, url)

        # Send POST request
        response = await self.client.post(url, content=payload, headers=headers)
        response.raise_for_status()
        return response

    async def close(self) -> None:
        """Gracefully shuts down the transport and connection client."""
        self.is_connected = False
        self.endpoint_received.clear()
        if self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except (asyncio.CancelledError, Exception):
                pass
            self.read_task = None
            
        if self.client:
            await self.client.aclose()
            self.client = None
            
        self.post_url = None
        logger.info("[yellow]SSE transport closed.[/yellow]")

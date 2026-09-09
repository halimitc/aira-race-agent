import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional
from config import config
from logger import logger
from agp.transport import SSETransport

class AGPMCPClient:
    """Model Context Protocol (MCP) client specifically configured for Rialo Agent Grand Prix."""
    
    def __init__(self, server_url: str, token: str):
        self.transport = SSETransport(server_url, token)
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.response_task: Optional[asyncio.Task] = None
        self.is_running = False
        self.is_initialized = False
        self.transport.on_disconnect = self._handle_disconnect
        self.transport.on_reconnect = self._handle_reconnect

    def _handle_reconnect(self) -> None:
        """Called when transport reconnects. Schedules initialization handshake in background if already initialized once."""
        if self.is_initialized:
            logger.info("[cyan]Re-establishing MCP Handshake after transport reconnection...[/cyan]")
            self.is_initialized = False
            asyncio.create_task(self._initialize_handshake())

    async def start(self) -> None:
        """Starts the transport, connects, and performs the MCP initialize handshake."""
        if self.is_running:
            return

        self.is_running = True
        await self.transport.connect()
        
        # Start response processing task
        self.response_task = asyncio.create_task(self._process_responses())

        # Perform MCP Handshake
        logger.info("[cyan]🏁 [PHASE 3/3] Performing Ignition Handshake (MCP Exchange)...[/cyan]")
        await self._initialize_handshake()

    def _handle_disconnect(self) -> None:
        """Called when transport disconnects. Clears pending requests with ConnectionError."""
        logger.warning("[yellow]Transport disconnected. Cancelling pending requests...[/yellow]")
        for req_id, future in list(self.pending_requests.items()):
            if not future.done():
                future.set_exception(ConnectionError("SSE Transport disconnected mid-request."))
            self.pending_requests.pop(req_id, None)

    async def _initialize_handshake(self) -> None:
        """Sends the initialize request and completes the handshake."""
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "agp-agent-champion",
                "version": "1.0.0"
            }
        }
        
        # Send initialize
        response = await self.send_request("initialize", init_params)
        server_version = response.get("protocolVersion")
        server_info = response.get("serverInfo", {})
        logger.info(
            f"[green]🟢 [PHASE 3/3] Engine Handshake Successful! (Grid Online)[/green]"
        )
        
        # Send notifications/initialized
        await self.send_notification("notifications/initialized", {})
        self.is_initialized = True

    async def _process_responses(self) -> None:
        """Loop to read JSON-RPC responses from transport and resolve pending futures."""
        while self.is_running:
            try:
                # Read next event data from transport queue
                event_data = await self.transport.incoming_queue.get()
                
                try:
                    payload = json.loads(event_data)
                except json.JSONDecodeError as parse_err:
                    logger.error(f"[red]Failed to parse incoming SSE message JSON: {parse_err}[/red]")
                    continue

                req_id = payload.get("id")
                if req_id is not None:
                    # Match request ID to pending future
                    future = self.pending_requests.pop(str(req_id), None)
                    if future and not future.done():
                        if "error" in payload:
                            future.set_exception(
                                RuntimeError(f"JSON-RPC Error: {payload['error']}")
                            )
                        else:
                            future.set_result(payload.get("result", {}))
                else:
                    # Handle notifications or requests from server if any
                    method = payload.get("method")
                    if method:
                        logger.debug(f"Received server notification/request: {method}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[red]Error in response processor: {e}[/red]")
                await asyncio.sleep(0.5)

    async def send_request(self, method: str, params: Dict[str, Any]) -> Any:
        """Sends a JSON-RPC 2.0 request and awaits the response."""
        req_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        }
        
        future = asyncio.get_running_loop().create_future()
        self.pending_requests[req_id] = future
        
        try:
            await self.transport.send_post(json.dumps(payload))
        except Exception as e:
            self.pending_requests.pop(req_id, None)
            raise ConnectionError(f"Failed to post JSON-RPC request: {e}") from e

        # Await the response matched in _process_responses (with timeout to prevent deadlocks)
        try:
            return await asyncio.wait_for(future, timeout=30.0)
        except asyncio.TimeoutError:
            self.pending_requests.pop(req_id, None)
            raise ConnectionError(f"JSON-RPC request '{method}' timed out after 30s.")

    async def send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Sends a JSON-RPC 2.0 notification (no response expected)."""
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params
        }
        await self.transport.send_post(json.dumps(payload))

    # ====================================================================
    # Official AGP MCP Tools Wrapper
    # ====================================================================

    async def _call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Calls a specific MCP tool via the tools/call method."""
        params = {
            "name": name,
            "arguments": arguments
        }
        response = await self.send_request("tools/call", params)
        # Check if response has isError flag
        if response.get("isError"):
            content = response.get("content", [])
            err_msg = content[0].get("text") if content else "Unknown error calling tool"
            raise RuntimeError(f"MCP Tool '{name}' returned error: {err_msg}")
        return response

    async def list_tracks(self) -> List[Dict[str, Any]]:
        """Lists available racing tracks."""
        response = await self._call_tool("list_tracks", {})
        res_data = self._extract_tool_result_json(response)
        if isinstance(res_data, dict) and "tracks" in res_data:
            return res_data["tracks"]
        return res_data

    async def start_track(self, track_id: str) -> Dict[str, Any]:
        """Registers/starts a race on a specific track."""
        response = await self._call_tool("start_track", {"trackId": track_id})
        return self._extract_tool_result_json(response)

    async def my_race(self) -> Dict[str, Any]:
        """Returns the state of the user's current active race."""
        response = await self._call_tool("my_race", {})
        return self._extract_tool_result_json(response)

    async def ask(self, question: str) -> Dict[str, Any]:
        """Asks the Oracle a YES/NO question (Costs real USDC)."""
        response = await self._call_tool("ask", {"question": question})
        return self._extract_tool_result_json(response)

    async def guess(self, answer: str) -> Dict[str, Any]:
        """Submits a guess for the secret of the current point (Free)."""
        response = await self._call_tool("guess", {"guess": answer})
        return self._extract_tool_result_json(response)

    async def sigil_balance(self) -> Dict[str, Any]:
        """Checks the current Sigil USDC balance."""
        response = await self._call_tool("sigil_balance", {})
        return self._extract_tool_result_json(response)

    async def track_state(self) -> Dict[str, Any]:
        """Checks the status of the current track/race progress."""
        response = await self._call_tool("track_state", {})
        return self._extract_tool_result_json(response)

    async def practice_ask(self, question: str) -> Dict[str, Any]:
        """Asks a YES/NO question for the practice point verification."""
        response = await self._call_tool("practice_ask", {"question": question})
        return self._extract_tool_result_json(response)

    async def practice_guess(self, guess: str) -> Dict[str, Any]:
        """Submits an answer for the practice point verification."""
        response = await self._call_tool("practice_guess", {"guess": guess})
        return self._extract_tool_result_json(response)

    def _extract_tool_result_json(self, tool_response: Dict[str, Any]) -> Any:
        """Helper to extract JSON data from the tool's returned content blocks or structuredContent."""
        if "structuredContent" in tool_response:
            return tool_response["structuredContent"]

        content = tool_response.get("content", [])
        if not content:
            return {}
        
        # Typically the result is returned in a text block
        first_item = content[0]
        if not isinstance(first_item, dict):
            return str(first_item)
        text_block = first_item.get("text", "")
        try:
            return json.loads(text_block)
        except json.JSONDecodeError:
            # If the output is a raw string instead of JSON, return it directly
            return text_block

    async def shutdown(self) -> None:
        """Gracefully shuts down response task and transport connection."""
        self.is_running = False
        if self.response_task:
            self.response_task.cancel()
            try:
                await self.response_task
            except asyncio.CancelledError:
                pass
            self.response_task = None
        await self.transport.close()

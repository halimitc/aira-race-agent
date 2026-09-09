import asyncio
import json
import os
import httpx
from typing import Optional
from config import config
from logger import logger

class ReasoningProvider:
    """Interchangeable reasoning provider for LLM API calls using httpx."""
    
    def __init__(self):
        self.provider = config.llm_provider
        if self.provider == "gemini":
            self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        elif self.provider == "claude":
            self.model = os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022")
        else:
            self.model = config.llm_model
        self._client: Optional[httpx.AsyncClient] = None
        self._last_call_time: float = 0.0
        # Adaptive rate limiter: starts fast, backs off on 429
        self._current_interval: float = 0.5  # Start at 0.5s (aggressive)
        self._min_interval_floor: float = 0.25  # Never go below this
        self._max_interval_ceiling: float = 8.0  # Never go above this
        self._consecutive_successes: int = 0

    @property
    def min_interval(self) -> float:
        """Returns the current adaptive interval between LLM calls."""
        return self._current_interval

    def _on_rate_limit_hit(self) -> None:
        """Called when HTTP 429 is received. Doubles the interval."""
        self._current_interval = min(self._current_interval * 2.0, self._max_interval_ceiling)
        self._consecutive_successes = 0
        logger.warning(f"[orange3]Rate limit hit! Increasing LLM interval to {self._current_interval:.2f}s[/orange3]")

    def _on_success(self) -> None:
        """Called on successful LLM call. Gradually decreases interval."""
        self._consecutive_successes += 1
        if self._consecutive_successes >= 5:
            self._current_interval = max(self._current_interval * 0.8, self._min_interval_floor)
            self._consecutive_successes = 0

    def _get_client(self) -> httpx.AsyncClient:
        """Returns or creates a persistent httpx client with connection pooling."""
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
            self._client = httpx.AsyncClient(timeout=30.0, limits=limits)
        return self._client

    async def close(self) -> None:
        """Closes the persistent HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def generate_response(self, system_prompt: str, user_prompt: str) -> str:
        """Sends a request to the configured LLM provider and returns the raw response string, with retry for transient network errors."""
        import time
        # Enforce provider-aware rate limiter
        now = time.time()
        elapsed = now - self._last_call_time
        interval = self.min_interval
        if elapsed < interval:
            wait_sec = interval - elapsed
            await asyncio.sleep(wait_sec)
        self._last_call_time = time.time()

        max_retries = 2
        for attempt in range(max_retries + 1):
            client = self._get_client()
            try:
                result = None
                if self.provider == "gemini":
                    result = await self._call_gemini(client, system_prompt, user_prompt)
                elif self.provider == "claude":
                    result = await self._call_claude(client, system_prompt, user_prompt)
                elif self.provider in ("openai", "openai_compatible"):
                    result = await self._call_openai(client, system_prompt, user_prompt)
                elif self.provider == "openrouter":
                    result = await self._call_openrouter(client, system_prompt, user_prompt)
                elif self.provider == "local":
                    result = await self._call_local(client, system_prompt, user_prompt)
                else:
                    raise ValueError(f"Unknown LLM provider: {self.provider}")
                self._on_success()
                return result
            except (httpx.HTTPError, httpx.TransportError, ConnectionError, OSError) as net_err:
                # Check for rate limit (429) and adapt interval
                if isinstance(net_err, httpx.HTTPStatusError) and net_err.response.status_code == 429:
                    self._on_rate_limit_hit()
                # Temporary failover: try alternate providers WITHOUT mutating self.provider permanently
                original_provider = self.provider
                original_model = self.model

                # Check if error is permanent billing/auth error (402 Payment Required, 401 Unauthorized)
                is_permanent_billing_err = False
                if isinstance(net_err, httpx.HTTPStatusError) and net_err.response.status_code in (401, 402):
                    is_permanent_billing_err = True

                if config.openai_api_key and self.provider not in ("openai", "openai_compatible"):
                    logger.warning(f"[orange3]Primary LLM ({self.provider}) error ({net_err}). Trying failover to OpenAI-compatible...[/orange3]")
                    try:
                        self.provider = "openai"
                        fallback_model = os.getenv("OPENAI_FALLBACK_MODEL", os.getenv("LLM_MODEL", "qwen/qwen3.8-27b"))
                        if "groq.com" in config.openai_base_url and ("llama" in fallback_model or "gpt-4" in fallback_model):
                            fallback_model = "qwen/qwen3.8-27b"
                        self.model = fallback_model
                        result = await self._call_openai(client, system_prompt, user_prompt)
                        if not is_permanent_billing_err:
                            self.provider = original_provider
                            self.model = original_model
                        else:
                            logger.warning(f"[yellow]Permanently switched LLM provider to 'openai' due to billing/auth error on '{original_provider}'.[/yellow]")
                        return result
                    except Exception as fallback_err:
                        logger.error(f"[red]OpenAI-compatible fallback also failed: {fallback_err}[/red]")
                        self.provider = original_provider
                        self.model = original_model
                elif config.anthropic_api_key and self.provider != "claude":
                    logger.warning(f"[orange3]Primary LLM ({self.provider}) error ({net_err}). Trying temporary failover to Claude...[/orange3]")
                    try:
                        self.provider = "claude"
                        self.model = "claude-3-5-haiku-20241022"
                        result = await self._call_claude(client, system_prompt, user_prompt)
                        self.provider = original_provider
                        self.model = original_model
                        return result
                    except Exception as fallback_err:
                        logger.error(f"[red]Claude fallback also failed: {fallback_err}[/red]")
                        self.provider = original_provider
                        self.model = original_model
                elif config.gemini_api_key and self.provider != "gemini":
                    logger.warning(f"[orange3]Primary LLM ({self.provider}) error ({net_err}). Trying temporary failover to Gemini...[/orange3]")
                    try:
                        self.provider = "gemini"
                        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
                        result = await self._call_gemini(client, system_prompt, user_prompt)
                        self.provider = original_provider
                        self.model = original_model
                        return result
                    except Exception as fallback_err:
                        logger.error(f"[red]Gemini fallback also failed: {fallback_err}[/red]")
                        self.provider = original_provider
                        self.model = original_model

                if is_permanent_billing_err:
                    logger.error(f"[bold red]Permanent billing/credit error ({net_err}) on '{self.provider}'. Fallbacks also failed. Stopping retries.[/bold red]")
                    raise RuntimeError(f"Permanent LLM Billing/Credit Error on provider '{self.provider}': {net_err}") from net_err

                if attempt < max_retries:
                    logger.warning(f"Transient network error calling LLM ({net_err}). Retrying in 1s (Attempt {attempt + 1}/{max_retries})...")
                    await asyncio.sleep(1.0)
                    continue
                logger.error(f"[red]LLM reasoning call failed after retries ({self.provider}): {net_err}[/red]")
                raise RuntimeError(f"Reasoning failure: {net_err}") from net_err
            except Exception as e:
                logger.error(f"[red]LLM reasoning call failed ({self.provider}): {e}[/red]", exc_info=True)
                raise RuntimeError(f"Reasoning failure: {e}") from e

    async def _call_gemini(self, client: httpx.AsyncClient, system_prompt: str, user_prompt: str) -> str:
        """Calls Gemini API directly using HTTP POST."""
        api_key = config.gemini_api_key
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")
        
        # We use generateContent endpoint
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={api_key}"
        
        payload = {
            "contents": [
                {
                    "parts": [{"text": user_prompt}]
                }
            ],
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            }
        }
        
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as err:
            logger.error(f"[red]Gemini API returned HTTP {err.response.status_code}: {err.response.text}[/red]")
            raise
        
        # Extract text content
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            if parts:
                return parts[0].get("text", "").strip()
        
        raise ValueError(f"Invalid Gemini response structure: {data}")

    async def _call_claude(self, client: httpx.AsyncClient, system_prompt: str, user_prompt: str) -> str:
        """Calls Anthropic Claude API directly with fallback to OpenRouter for Claude Haiku."""
        api_key = config.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not configured.")

        # First attempt: Anthropic Direct API
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        payload = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 1024,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}]
        }
        
        try:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            content = data.get("content", [])
            if content:
                return content[0].get("text", "").strip()
        except httpx.HTTPStatusError as err:
            logger.warning(f"[orange3]Anthropic Direct API status {err.response.status_code}. Trying OpenRouter Haiku fallback...[/orange3]")
            # Fallback attempt: OpenRouter API with anthropic/claude-3-haiku
            openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
            or_headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            or_payload = {
                "model": "anthropic/claude-3-haiku",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            }
            or_resp = await client.post(openrouter_url, json=or_payload, headers=or_headers)
            or_resp.raise_for_status()
            or_data = or_resp.json()
            choices = or_data.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "").strip()
            raise ValueError(f"Invalid OpenRouter Haiku response structure: {or_data}")
            
        raise ValueError("Invalid Claude response structure.")

    async def _call_openai(self, client: httpx.AsyncClient, system_prompt: str, user_prompt: str) -> str:
        """Calls OpenAI Chat Completion API or OpenAI Compatible API."""
        api_key = config.openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not configured.")

        url = f"{config.openai_base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
            
        raise ValueError(f"Invalid OpenAI response structure: {data}")

    async def _call_openrouter(self, client: httpx.AsyncClient, system_prompt: str, user_prompt: str) -> str:
        """Calls OpenRouter Chat Completion API."""
        api_key = config.openrouter_api_key
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not configured.")

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        }
        
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "").strip()
            
        raise ValueError(f"Invalid OpenRouter response structure: {data}")

    async def _call_local(self, client: httpx.AsyncClient, system_prompt: str, user_prompt: str) -> str:
        """Calls a local Ollama or Llama.cpp instance (defaulting to Ollama at localhost:11434)."""
        url = "http://localhost:11434/api/chat"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "format": "json"
        }
        
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        
        message = data.get("message", {})
        if message:
            return message.get("content", "").strip()
            
        raise ValueError(f"Invalid Local Ollama response structure: {data}")

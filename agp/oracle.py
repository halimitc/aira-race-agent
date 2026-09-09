import asyncio
from typing import Dict, Any, Optional
from logger import logger
from agp.client import AGPMCPClient

class UnsafeBalanceError(Exception):
    """Raised when Sigil balance is too low to safely ask questions."""
    pass

class OracleGateway:
    """Resilient gatekeeper for communication with the AGP Oracle."""
    
    def __init__(self, client: AGPMCPClient, min_balance_usdc: float = 0.01):
        self.client = client
        self.min_balance_usdc = min_balance_usdc
        self.lock = asyncio.Lock()  # Sequential ask enforcement
        self.local_cache: Dict[str, str] = {}  # Map: question -> answer
        self.last_asked_question: Optional[str] = None
        # Cached balance to avoid checking every ask
        self._cached_balance: float = 0.0
        self._balance_check_count: int = 0

    def clear_cache(self) -> None:
        """Clears the local Oracle answer cache. Must be called on checkpoint transitions."""
        self.local_cache.clear()
        logger.info("[cyan]Oracle answer cache cleared for new checkpoint.[/cyan]")

    async def check_balance(self) -> float:
        """Queries the current Sigil balance and checks if it is safe to proceed."""
        try:
            balance_info = await self.client.sigil_balance()
            
            # Server returns: {"login": "halimitc", "sigilBalance": {"balanceUsd": 0, "creditRemainingUsd": 1, ...}}
            sigil = balance_info.get("sigilBalance", {})
            balance_usd = float(sigil.get("balanceUsd") or 0.0)
            credit_remaining = float(sigil.get("creditRemainingUsd") or 0.0)
            total_available = balance_usd + credit_remaining
            currency = sigil.get("currency") or "AGP"
            
            logger.info(f"Sigil Balance: {balance_usd:.4f} + {credit_remaining:.4f} credit = {total_available:.4f} {currency} total")
            
            if total_available < self.min_balance_usdc:
                raise UnsafeBalanceError(
                    f"Sigil balance ({total_available:.4f} {currency}) is below safe limit ({self.min_balance_usdc:.4f} {currency})."
                )
            
            self._cached_balance = total_available
            return total_available
        except UnsafeBalanceError:
            raise
        except Exception as e:
            logger.warning(f"Failed to verify Sigil balance: {e}. Using cached value ${self._cached_balance:.4f}.")
            if self._cached_balance > 0:
                return self._cached_balance
            # If no cached value, assume safe to not block the race
            return self.min_balance_usdc

    def get_cached_balance(self) -> float:
        """Returns the last known balance without making an API call."""
        return self._cached_balance

    async def ask(self, question: str, force_retry: bool = False) -> str:
        """Asks a question to the Oracle. Enforces sequential queries and cached retries."""
        # Clean up question formatting
        question = question.strip()
        
        # Check local cache first
        if question in self.local_cache and not force_retry:
            logger.info(f"[green]Oracle cache hit: '{question}' -> {self.local_cache[question]}[/green]")
            return self.local_cache[question]

        async with self.lock:
            # Only check balance periodically (every 10 asks) to reduce API overhead
            self._balance_check_count += 1
            if self._balance_check_count >= 10 or self._cached_balance <= 0:
                await self.check_balance()
                self._balance_check_count = 0
            
            logger.info(f"[yellow]Asking Oracle: '{question}'...[/yellow]")
            self.last_asked_question = question
            
            try:
                # Call client ask tool
                result = await self.client.ask(question)
                
                # Parse answer from various possible response formats
                answer = self._parse_answer(result)
                
                self.local_cache[question] = answer
                logger.info(f"[green]Oracle Answer: {answer}[/green]")
                return answer
                
            except (asyncio.TimeoutError, ConnectionError) as conn_err:
                logger.warning(
                    f"[orange3]Connection failure during ask(): {conn_err}. "
                    f"Retrying identical question: '{question}'...[/orange3]"
                )
                # Re-try the EXACT same question string to hit Oracle's server-side cache for free recovery
                return await self._retry_identical_ask(question)
            except Exception as e:
                logger.error(f"[red]Error asking Oracle: {e}[/red]")
                raise

    def _parse_answer(self, result: Any) -> str:
        """Parses the Oracle response into a YES/NO string, handling multiple formats."""
        answer = ""
        if isinstance(result, dict):
            # Case-insensitive key lookup (handles VERDICT, Verdict, verdict, etc.)
            result_lower = {str(k).lower(): v for k, v in result.items()}
            for key in ("verdict", "answer", "response", "text", "result"):
                val = result_lower.get(key)
                if val is not None and str(val).strip():
                    answer = str(val).strip().upper()
                    break
            # If none of those keys worked, check if raw string contains clear verdict
            if not answer:
                answer = str(result).upper()
        elif isinstance(result, str):
            answer = result.strip().upper()
        
        # Normalize common variants (exact match first)
        if answer in ("YES", "TRUE", "CORRECT", "Y"):
            return "YES"
        elif answer in ("NO", "FALSE", "INCORRECT", "N"):
            return "NO"
        elif answer in ("MAYBE", "UNKNOWN", "UNSURE", "UNCERTAIN"):
            logger.warning(f"[orange3]Oracle returned ambiguous answer: '{answer}'. Treating as UNKNOWN.[/orange3]")
            return "UNKNOWN"
        
        # Handle conversational responses like "Yes, it is in North America"
        if answer.startswith("YES"):
            return "YES"
        elif answer.startswith("NO"):
            return "NO"
        elif answer.startswith("MAYBE") or answer.startswith("UNKNOWN"):
            logger.warning(f"[orange3]Oracle returned ambiguous answer: '{answer}'. Treating as UNKNOWN.[/orange3]")
            return "UNKNOWN"
        
        # Last resort: search for YES/NO keywords anywhere in the response
        if "YES" in answer and "NO" not in answer:
            return "YES"
        elif "NO" in answer and "YES" not in answer:
            return "NO"
        
        # Final fallback: treat unrecognized answers as UNKNOWN instead of crashing
        logger.warning(f"[orange3]Oracle returned unrecognized answer: '{answer}' (Raw: {result}). Treating as UNKNOWN.[/orange3]")
        return "UNKNOWN"

    async def _retry_identical_ask(self, question: str, max_retries: int = 3) -> str:
        """Performs up to max_retries with the identical question string for server-side cache recovery."""
        for attempt in range(1, max_retries + 1):
            backoff = 0.5 * (2 ** (attempt - 1))
            await asyncio.sleep(backoff)
            try:
                result = await self.client.ask(question)
                answer = self._parse_answer(result)
                
                self.local_cache[question] = answer
                logger.info(f"[green]Oracle Answer recovered (free, attempt {attempt}/{max_retries}): {answer}[/green]")
                return answer
            except Exception as e:
                logger.warning(f"[orange3]Retry attempt {attempt}/{max_retries} for ask() failed: {e}[/orange3]")
                if attempt == max_retries:
                    logger.error(f"[red]Failed to recover Oracle question after {max_retries} retries: {e}[/red]")
                    raise

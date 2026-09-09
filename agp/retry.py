import asyncio
import random
from typing import Callable, TypeVar, Any, Awaitable
from logger import logger

T = TypeVar('T')

async def retry_async(
    func: Callable[[], Awaitable[T]],
    retries: int = 5,
    initial_delay: float = 1.0,
    max_delay: float = 32.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    error_types: tuple = (Exception,)
) -> T:
    """Executes an async function with exponential backoff and jitter on failure."""
    delay = initial_delay
    
    for attempt in range(retries):
        try:
            return await func()
        except error_types as e:
            if attempt == retries - 1:
                logger.error(f"[red]Failed after {retries} attempts: {e}[/red]")
                raise e
            
            # Calculate backoff delay
            current_delay = delay
            if jitter:
                current_delay *= random.uniform(0.5, 1.5)
            current_delay = min(current_delay, max_delay)
            
            logger.warning(
                f"[yellow]Attempt {attempt + 1} failed: {e}. "
                f"Retrying in {current_delay:.2f} seconds...[/yellow]"
            )
            await asyncio.sleep(current_delay)
            
            delay *= backoff_factor
            
    # Fallback to raising exception
    raise RuntimeError("Retry loop completed without returning or raising.")

import json
import time
from pathlib import Path
from typing import Any, Optional, Dict
from config import config
from logger import logger

class FileCache:
    """Persistent, file-based cache for API queries and heavy LLM operations."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or config.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.memory_cache: Dict[str, Dict[str, Any]] = {}
        self._load_memory_cache()

    def _get_cache_path(self, key: str) -> Path:
        # Sanitize key for filesystem
        safe_key = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)
        return self.cache_dir / f"cache_{safe_key}.json"

    def _load_memory_cache(self) -> None:
        """Prefills memory cache with existing file keys for faster reads."""
        for path in self.cache_dir.glob("cache_*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Key is stored inside the file metadata
                    key = data.get("key")
                    if key:
                        self.memory_cache[key] = data
            except Exception:
                pass

    def get(self, key: str) -> Optional[Any]:
        """Retrieves a value from memory cache or file cache if not expired."""
        data = self.memory_cache.get(key)
        
        # If not in memory, try loading from disk
        if not data:
            path = self._get_cache_path(key)
            if path.exists():
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.memory_cache[key] = data
                except Exception as e:
                    logger.warning(f"Error reading cache file {path}: {e}")
                    return None

        if data:
            expire_at = data.get("expire_at")
            if expire_at is not None and time.time() > expire_at:
                # Expired cache item
                self.delete(key)
                return None
            return data.get("value")
        return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """Saves a value to both memory cache and persistent disk cache."""
        expire_at = (time.time() + ttl_seconds) if ttl_seconds is not None else None
        
        data = {
            "key": key,
            "value": value,
            "expire_at": expire_at,
            "created_at": time.time()
        }
        
        # Save in memory
        self.memory_cache[key] = data
        
        # Save to disk
        path = self._get_cache_path(key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to write cache file {path}: {e}")

    def delete(self, key: str) -> None:
        """Deletes a key from memory and disk cache."""
        self.memory_cache.pop(key, None)
        path = self._get_cache_path(key)
        if path.exists():
            try:
                path.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete cache file {path}: {e}")

    def clear(self) -> None:
        """Clears all cached items on disk and memory."""
        self.memory_cache.clear()
        for path in self.cache_dir.glob("cache_*.json"):
            try:
                path.unlink()
            except Exception:
                pass
        logger.info("[yellow]Local file cache cleared.[/yellow]")

# Global cache instance
cache = FileCache()

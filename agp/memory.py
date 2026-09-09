import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from config import config
from logger import logger

class RaceMemory:
    """Manages persistence and recovery of the active race state."""
    
    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = filepath or config.memory_file
        self.state: Dict[str, Any] = self._get_default_state()

    def _get_default_state(self) -> Dict[str, Any]:
        """Returns clean state structure."""
        return {
            "track_id": None,
            "current_point": 0,
            "hint": "",
            "history": [],  # List of Dict: {"question": "...", "answer": "..."}
            "candidates": [],  # List of str
            "candidate_probabilities": {},  # Map: entity -> probability
            "question_count": 0,
            "guess_count": 0,
            "usdc_spent": 0.0,
            "start_time": 0.0,
            "elapsed_time": 0.0,
            "status": "idle"  # idle, racing, finished
        }

    def reset(self) -> None:
        """Clears memory file and state."""
        self.state = self._get_default_state()
        if self.filepath.exists():
            try:
                self.filepath.unlink()
            except Exception as e:
                logger.error(f"Failed to delete memory file: {e}")
        logger.info("[yellow]Race memory reset successfully.[/yellow]")

    def save(self) -> None:
        """Saves current state dictionary to the JSON memory file (atomic write)."""
        try:
            # Write to temp file first, then rename (atomic on most OS)
            tmp_path = self.filepath.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
            # BUG FIX 7: Use os.replace() instead of Path.replace() for Windows compatibility
            import os
            os.replace(str(tmp_path), str(self.filepath))
        except Exception as e:
            logger.error(f"[red]Failed to save race memory file: {e}[/red]")

    def load(self) -> bool:
        """Loads state dictionary from file. Returns True if state was loaded successfully."""
        if not self.filepath.exists():
            return False
            
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                loaded_state = json.load(f)
                # Verify keys structure
                if isinstance(loaded_state, dict) and "current_point" in loaded_state:
                    self.state = loaded_state
                    logger.info(
                        f"[green]Successfully loaded previous race memory from file. "
                        f"Track: {self.state.get('track_id', 'Unknown')}, Point: {self.state.get('current_point', 0)}[/green]"
                    )
                    return True
        except Exception as e:
            logger.error(f"Error loading race memory file: {e}")
        return False

import time
import json
from pathlib import Path
from typing import Dict, Any, Optional
from config import config
from logger import logger

class RaceMetrics:
    """Collects, aggregates, and stores analytical performance metrics of races."""
    
    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = filepath or config.metrics_file
        self.start_time: float = 0.0
        self.total_time: float = 0.0
        
        self.asks_count: int = 0
        self.guesses_count: int = 0
        self.correct_guesses_count: int = 0
        
        self.total_usdc_spent: float = 0.0
        
        # Latency statistics
        self.total_latency: float = 0.0
        
        # Entropy & Pruning statistics
        self.total_info_gain: float = 0.0
        self.total_reduction_rate: float = 0.0
        
        # Cache & Reconnect stats
        self.cache_hits: int = 0
        self.cache_misses: int = 0
        self.reconnect_count: int = 0

    def start_race(self) -> None:
        """Starts the race timer and resets metrics."""
        self.start_time = time.time()
        self.total_time = 0.0
        self.asks_count = 0
        self.guesses_count = 0
        self.correct_guesses_count = 0
        self.total_usdc_spent = 0.0
        self.total_latency = 0.0
        self.total_info_gain = 0.0
        self.total_reduction_rate = 0.0
        self.cache_hits = 0
        self.cache_misses = 0
        self.reconnect_count = 0

    def stop_race(self) -> None:
        """Stops the race timer and saves metrics."""
        if self.start_time > 0:
            self.total_time = time.time() - self.start_time
            self.save()

    def record_ask(self, latency: float, cost: float, info_gain: float, reduction_rate: float) -> None:
        """Logs metrics associated with a paid Oracle ask query."""
        self.asks_count += 1
        self.total_latency += latency
        self.total_usdc_spent += cost
        self.total_info_gain += info_gain
        self.total_reduction_rate += reduction_rate

    def record_guess(self, is_correct: bool, cost: float = 0.0) -> None:
        """Logs metrics associated with a guess submission."""
        self.guesses_count += 1
        self.total_usdc_spent += cost
        if is_correct:
            self.correct_guesses_count += 1

    def record_cache_lookup(self, hit: bool) -> None:
        """Logs a local cache lookup result."""
        if hit:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

    def record_reconnect(self) -> None:
        """Logs a transport reconnect event."""
        self.reconnect_count += 1

    def get_summary(self) -> Dict[str, Any]:
        """Aggregates all collected statistics into a structured dictionary."""
        avg_latency = self.total_latency / self.asks_count if self.asks_count > 0 else 0.0
        avg_info_gain = self.total_info_gain / self.asks_count if self.asks_count > 0 else 0.0
        avg_reduction = self.total_reduction_rate / self.asks_count if self.asks_count > 0 else 0.0
        
        guess_accuracy = (
            self.correct_guesses_count / self.guesses_count if self.guesses_count > 0 else 0.0
        )
        
        total_cache_ops = self.cache_hits + self.cache_misses
        cache_ratio = self.cache_hits / total_cache_ops if total_cache_ops > 0 else 0.0
        
        # Estimate USDC saved by guessing compared to asking (each guess replaces at least 1 expected ask)
        estimated_usdc_saved = (self.guesses_count - self.correct_guesses_count) * 0.001

        return {
            "total_race_time_seconds": self.total_time,
            "total_asks": self.asks_count,
            "total_guesses": self.guesses_count,
            "correct_guesses": self.correct_guesses_count,
            "guess_accuracy": guess_accuracy,
            "total_usdc_spent": self.total_usdc_spent,
            "estimated_usdc_saved": max(0.0, estimated_usdc_saved),
            "average_latency_seconds": avg_latency,
            "average_information_gain_bits": avg_info_gain,
            "average_candidate_reduction_rate": avg_reduction,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_ratio": cache_ratio,
            "reconnect_count": self.reconnect_count
        }

    def save(self) -> None:
        """Writes current metrics summary to JSON file."""
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.get_summary(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save metrics file: {e}")

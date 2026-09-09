import math
from typing import Dict, Any
from config import config
from logger import logger

class CostOptimizer:
    """Calculates trade-offs between paid Oracle questions and paid/free guesses."""
    
    def __init__(self, ask_cost_usdc: float = 0.001, guess_cost_usdc: float = 0.0, spend_cap_usdc: float = None):
        """Initialize with track costs. Defaults match Day 3/4 track pricing."""
        self.ask_cost_usdc = ask_cost_usdc
        self.guess_cost_usdc = guess_cost_usdc
        self.spend_cap_usdc = spend_cap_usdc  # None = unlimited
        self.total_spent_usdc = 0.0
        
        # Base thresholds for profiles
        self.profile_thresholds = {
            "conservative": 0.95,
            "balanced": 0.80,
            "aggressive": 0.50,
            "ultra_aggressive": 0.15
        }

    def get_profile_threshold(self) -> float:
        """Returns the base confidence threshold for the configured race profile.
        If guesses are paid, dynamically downgrades ultra_aggressive to balanced to protect USDC balance."""
        profile = config.race_profile
        if self.guess_cost_usdc > 0 and profile == "ultra_aggressive":
            logger.warning("[orange3]Paid guesses detected! Dynamically downgrading strategy from 'ultra_aggressive' to 'balanced' to protect USDC balance.[/orange3]")
            profile = "balanced"
        return self.profile_thresholds.get(profile, 0.80)

    def can_afford_ask(self) -> bool:
        """Checks if the agent can afford another paid ask within the spend cap."""
        if self.spend_cap_usdc is not None:
            remaining = self.spend_cap_usdc - self.total_spent_usdc
            if remaining < self.ask_cost_usdc:
                logger.warning(f"[orange3]SpendCap exhausted! Spent: ${self.total_spent_usdc:.4f} / Cap: ${self.spend_cap_usdc:.4f}. Cannot ask.[/orange3]")
                return False
        return True

    def record_spend(self, amount: float) -> None:
        """Records spending against the cap."""
        self.total_spent_usdc += amount

    def should_guess(
        self,
        top_candidate_prob: float,
        remaining_candidates_count: int,
        sigil_balance: float
    ) -> bool:
        """Determines if the agent should submit a guess instead of asking another question."""
        if remaining_candidates_count == 0:
            return False

        # If spend cap is exhausted, we MUST guess (can't ask anymore)
        if not self.can_afford_ask():
            logger.warning(f"[orange3]SpendCap reached! Forcing GUESS — no more asks allowed.[/orange3]")
            return True

        # If only 1 candidate remains, we must guess it (100% confidence)
        if remaining_candidates_count == 1:
            logger.info("Only 1 candidate remains. Deciding to guess.")
            return True

        # BUG FIX: If balance is zero or near-zero, we MUST guess (asking costs money we don't have)
        if sigil_balance <= 0.001:
            logger.warning(f"[orange3]Balance critical (${sigil_balance:.4f}). Forcing GUESS to avoid failed ask.[/orange3]")
            return True

        # BUG FIX: If guesses are free, be more aggressive about guessing
        if self.guess_cost_usdc <= 0 and top_candidate_prob >= 0.05:
            logger.info(f"[green]Free guesses available. Guessing with probability {top_candidate_prob:.2%}[/green]")
            return True

        base_threshold = self.get_profile_threshold()
        
        # Calculate Expected Cost of both paths:
        # Path A: Ask questions until resolved, then submit 1 guess at the end
        estimated_asks_needed = max(1.0, math.log2(remaining_candidates_count))
        expected_cost_ask_path = (estimated_asks_needed * self.ask_cost_usdc) + self.guess_cost_usdc
        
        # Path B: Guess the top candidate immediately.
        # If correct (p): cost is guess_cost
        # If incorrect (1-p): cost is guess_cost + cost to resolve remaining (M-1) candidates
        estimated_remaining_asks = max(0.0, math.log2(max(1, remaining_candidates_count - 1)))
        expected_cost_remaining = (estimated_remaining_asks * self.ask_cost_usdc) + self.guess_cost_usdc
        expected_cost_guess_path = self.guess_cost_usdc + (1.0 - top_candidate_prob) * expected_cost_remaining
        
        logger.info(
            f"Cost Analysis: Remaining: {remaining_candidates_count} | Top Prob: {top_candidate_prob:.2%} | "
            f"Exp. Cost Ask Path: ${expected_cost_ask_path:.6f} USDC | "
            f"Exp. Cost Guess Path: ${expected_cost_guess_path:.6f} USDC"
        )

        # Dynamic threshold modification based on wallet balance and SpendCap consumption
        adjusted_threshold = base_threshold
        
        # P1-2 FIX: SpendCap ratio monitoring (AGP Winner strategy)
        if self.spend_cap_usdc and self.spend_cap_usdc > 0:
            spent_ratio = self.total_spent_usdc / self.spend_cap_usdc
            if spent_ratio >= 0.90:
                adjusted_threshold = min(adjusted_threshold, 0.15)
                logger.warning(f"[bold red]⚠️ CRITICAL BUDGET ALERT! {spent_ratio:.1%} of SpendCap consumed. Forcing ultra-aggressive guessing (Threshold: {adjusted_threshold:.2%})[/bold red]")
            elif spent_ratio >= 0.70:
                adjusted_threshold = min(adjusted_threshold, base_threshold * 0.70)
                logger.warning(f"[orange3]⚠️ BUDGET WARNING: {spent_ratio:.1%} of SpendCap consumed. Switching to budget-conservation mode (Threshold: {adjusted_threshold:.2%})[/orange3]")

        if sigil_balance < 0.02:
            # If balance is getting low, be slightly more conservative if guesses are expensive,
            # or more aggressive if guesses are free.
            if self.guess_cost_usdc > self.ask_cost_usdc:
                # Guesses are expensive; raise threshold to avoid wasting money on wrong guesses
                adjusted_threshold = min(0.98, adjusted_threshold * 1.1)
                logger.warning(f"Low Sigil balance & expensive guesses! Raising guess threshold to {adjusted_threshold:.2%}")
            else:
                # Guesses are cheap/free; lower threshold to save money
                adjusted_threshold = max(0.15, adjusted_threshold * 0.7)
                logger.warning(f"Low Sigil balance & cheap guesses! Lowering guess threshold to {adjusted_threshold:.2%}")

        # Deciding factors:
        # 1. Probability exceeds adjusted profile threshold
        # 2. Expected cost of guessing is lower than asking
        if top_candidate_prob >= adjusted_threshold or expected_cost_guess_path < expected_cost_ask_path:
            logger.info(
                f"[green]Decision: GUESS (Confidence {top_candidate_prob:.2%} >= Threshold {adjusted_threshold:.2%} "
                f"or Guess Path ${expected_cost_guess_path:.6f} < Ask Path ${expected_cost_ask_path:.6f})[/green]"
            )
            return True
            
        logger.info(
            f"[cyan]Decision: ASK (Confidence {top_candidate_prob:.2%} < Threshold {adjusted_threshold:.2%} "
            f"and Guess Path ${expected_cost_guess_path:.6f} >= Ask Path ${expected_cost_ask_path:.6f})[/cyan]"
        )
        return False

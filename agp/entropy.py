import asyncio
import json
import math
from typing import List, Dict, Tuple, Optional
from logger import logger
from agp.reasoning_provider import ReasoningProvider

class EntropyEngine:
    """Calculates Shannon Entropy and Expected Information Gain for candidate questions."""
    
    def __init__(self, provider: ReasoningProvider):
        self.provider = provider

    async def score_question(
        self, question: str, candidates: List[str]
    ) -> Dict[str, float]:
        """Calculates entropy, expected info gain, and partition metrics for a question."""
        n = len(candidates)
        if n <= 1:
            return {"entropy": 0.0, "yes_count": 0.0, "no_count": 0.0, "info_gain": 0.0, "partition_quality": 0.0}

        # Query LLM to partition candidates into YES/NO sets
        system_prompt = (
            "You are the Entropy Partitioning Engine of an autonomous Agent Grand Prix racing agent.\n"
            "Your job is to partition a list of candidate entities based on whether the answer to a specific question is YES or NO.\n"
            "Output a JSON object containing exactly two keys: 'yes' (list of entities where question is YES) and 'no' (list of entities where question is NO).\n"
            "Every entity in the provided list MUST be categorized into either 'yes' or 'no'. Do not include explanation."
        )
        
        # Limit candidates sent to LLM to prevent token blowup
        candidate_sample = candidates[:30]
        
        user_prompt = (
            f"Question: '{question}'\n"
            f"Candidates: {json.dumps(candidate_sample)}\n"
            "Partition the candidates list:"
        )

        yes_set = []
        no_set = []
        try:
            response_text = await self.provider.generate_response(system_prompt, user_prompt)
            
            from agp.json_utils import clean_and_parse_json
            data = clean_and_parse_json(response_text)
            yes_set = data.get("yes", [])
            no_set = data.get("no", [])
            
            # Validate: only count candidates that are actually in our list
            candidate_set_lower = {c.lower() for c in candidate_sample}
            yes_set = [y for y in yes_set if str(y).lower() in candidate_set_lower]
            no_set = [item for item in no_set if str(item).lower() in candidate_set_lower]
            
        except Exception as e:
            logger.warning(f"Failed to partition candidates for question '{question}': {e}. Scoring as 0 (unusable).")
            # BUG FIX: Return score of 0 on failure, NOT a 50/50 split (which gives max score)
            return {"entropy": 0.0, "yes_count": 0.0, "no_count": 0.0, "info_gain": 0.0, "partition_quality": 0.0}

        # Calculate counts
        yes_count = len(yes_set)
        no_count = len(no_set)
        
        total = yes_count + no_count
        if total == 0:
            return {"entropy": 0.0, "yes_count": 0.0, "no_count": 0.0, "info_gain": 0.0, "partition_quality": 0.0}
            
        p_yes = yes_count / total
        p_no = no_count / total

        # Shannon Entropy of the binary split
        entropy = 0.0
        if p_yes > 0.0 and p_no > 0.0:
            entropy = - (p_yes * math.log2(p_yes) + p_no * math.log2(p_no))

        # Expected Information Gain is equivalent to the entropy of the binary split
        info_gain = entropy

        # Partition Quality (ranges 0 to 1, peaks at 50/50 split)
        partition_quality = 1.0 - abs(p_yes - 0.5) * 2.0

        return {
            "entropy": entropy,
            "info_gain": info_gain,
            "yes_count": float(yes_count),
            "no_count": float(no_count),
            "partition_quality": partition_quality
        }

    async def select_best_question_fused(
        self,
        hint: str,
        history: List[Dict[str, str]],
        candidates: List[str],
        fallback_questions: Optional[List[str]] = None
    ) -> Tuple[str, Dict[str, float]]:
        """Fast Single-Pass Prompt Fusion: Generates AND scores the optimal 50/50 binary question in a single LLM call.
        Includes an automatic fallback to multi-step parallel entropy engine if single-pass fails."""
        if not candidates:
            raise ValueError("No candidates provided for Single-Pass Fusion.")

        try:
            sample_candidates = candidates[:30]
            # Send full history (capped at 15 for token efficiency) so LLM avoids redundant questions
            history_cap = history[-15:] if history else []
            history_str = json.dumps(history_cap) if history_cap else "None"
            
            system_prompt = (
                "You are the Ultra-Fast Single-Pass Entropy Engine of an autonomous AGP racing agent.\n"
                "Your task is to analyze candidate entities and return the single BEST YES/NO question that splits the candidate list as close to a 50/50 ratio as possible.\n"
                "Output MUST be valid JSON with keys:\n"
                '{"best_question": "...", "reasoning": "...", "estimated_yes_count": <int>, "estimated_no_count": <int>}\n'
                "Do not include markdown code block quotes around the JSON."
            )
            
            user_prompt = (
                f"Hint: '{hint}'\n"
                f"Recent History: {history_str}\n"
                f"Active Candidates ({len(sample_candidates)}): {json.dumps(sample_candidates)}\n"
                "Formulate and select the single optimal 50/50 binary YES/NO question:"
            )

            response_text = await self.provider.generate_response(system_prompt, user_prompt)
            
            from agp.json_utils import clean_and_parse_json
            data = clean_and_parse_json(response_text)
            best_question = str(data.get("best_question", "")).strip()
            
            if not best_question:
                raise ValueError("LLM returned empty best_question")
                
            raw_yes = data.get("estimated_yes_count")
            raw_no = data.get("estimated_no_count")
            yes_c = float(raw_yes) if raw_yes is not None else float(len(sample_candidates) / 2)
            no_c = float(raw_no) if raw_no is not None else float(len(sample_candidates) / 2)
            
            total = yes_c + no_c
            p_yes = yes_c / total if total > 0 else 0.5
            p_no = no_c / total if total > 0 else 0.5
            
            entropy = 0.0
            if p_yes > 0.0 and p_no > 0.0:
                entropy = - (p_yes * math.log2(p_yes) + p_no * math.log2(p_no))
                
            score = {
                "entropy": entropy,
                "info_gain": entropy,
                "yes_count": yes_c,
                "no_count": no_c,
                "partition_quality": 1.0 - abs(p_yes - 0.5) * 2.0
            }
            
            logger.info(
                f"[bold green][FAST] Single-Pass Fusion Selected: '{best_question}' "
                f"(Est. Split: {yes_c:.0f} YES / {no_c:.0f} NO | Info Gain: {entropy:.4f})[/bold green]"
            )
            return best_question, score

        except Exception as e:
            logger.warning(f"[yellow]Single-Pass Fusion failed ({e}). Falling back to multi-step parallel entropy engine...[/yellow]")
            if fallback_questions:
                return await self.select_best_question(fallback_questions, candidates)
            else:
                raise

    async def select_best_question(
        self, questions: List[str], candidates: List[str]
    ) -> Tuple[str, Dict[str, float]]:
        """Evaluates multiple questions IN PARALLEL and returns the one with the highest information gain."""
        if not questions:
            raise ValueError("No questions provided for evaluation.")
            
        # Limit evaluation to top 5 questions to save API time
        eval_list = questions[:5]
        
        # BUG FIX: Score all questions in parallel using asyncio.gather()
        scoring_tasks = [self.score_question(q, candidates) for q in eval_list]
        scores = await asyncio.gather(*scoring_tasks, return_exceptions=True)
        
        best_question = eval_list[0]
        best_score = {"entropy": -1.0, "info_gain": -1.0}
        
        for i, score in enumerate(scores):
            if isinstance(score, Exception):
                logger.warning(f"Scoring failed for question '{eval_list[i]}': {score}")
                continue
                
            logger.info(f"Question: '{eval_list[i]}' -> Info Gain: {score['info_gain']:.4f} (Split: {score['yes_count']:.0f} YES / {score['no_count']:.0f} NO)")
            
            if score["info_gain"] > best_score["info_gain"]:
                best_score = score
                best_question = eval_list[i]

        return best_question, best_score

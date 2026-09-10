import json
from typing import Dict, List, Set, Any
from logger import logger
from agp.reasoning_provider import ReasoningProvider

class CandidateManager:
    """Manages the set of active candidate entities, their probabilities, and elimination history."""
    
    def __init__(self, provider: ReasoningProvider):
        self.provider = provider
        self.candidates: Dict[str, float] = {}  # Map: entity -> confidence
        self.elimination_history: Dict[str, str] = {}  # Map: entity -> reason
        self.supporting_answers: Dict[str, List[str]] = {}  # Map: entity -> list of matching Q&As
        self.contradicting_answers: Dict[str, List[str]] = {}  # Map: entity -> list of conflicting Q&As

    def set_candidates(self, candidate_list: List[str]) -> None:
        """Initializes candidate dictionary with equal prior probabilities."""
        if not candidate_list:
            self.candidates = {}
            return
            
        prior = 1.0 / len(candidate_list)
        self.candidates = {c: prior for c in candidate_list}
        self.elimination_history = {}
        self.supporting_answers = {c: [] for c in candidate_list}
        self.contradicting_answers = {c: [] for c in candidate_list}
        logger.info(f"Initialized Candidate Manager with {len(candidate_list)} entities.")

    def get_active_candidates(self) -> List[str]:
        """Returns the list of active (non-eliminated) candidates sorted by confidence."""
        active = [c for c, conf in self.candidates.items() if conf > 0.0]
        return sorted(active, key=lambda c: self.candidates[c], reverse=True)

    def apply_partition(self, question: str, answer: str, yes_candidates: List[str], no_candidates: List[str]) -> bool:
        """Fast local partitioning: prunes candidates in 0ms using the pre-computed partition from Single-Pass Fusion.
        Returns True if successful, False if fallback LLM consistency check is required."""
        active_list = self.get_active_candidates()
        if not active_list or not yes_candidates or not no_candidates:
            return False

        ans_clean = str(answer).strip().upper()
        yes_set = {str(c).strip().lower() for c in yes_candidates if str(c).strip()}
        no_set = {str(c).strip().lower() for c in no_candidates if str(c).strip()}
        
        eliminated_set = set()
        if "YES" in ans_clean:
            eliminated_set = no_set
        elif "NO" in ans_clean:
            eliminated_set = yes_set
        else:
            return False

        if not eliminated_set:
            return False

        eliminated_count = 0
        new_active = []
        reason = f"Partition: Q: '{question}' -> A: {ans_clean}"
        for c in active_list:
            c_low = c.strip().lower()
            if c_low in eliminated_set or any(c_low == e or (len(c_low) > 3 and c_low in e) for e in eliminated_set):
                self.elimination_history[c] = reason
                self.candidates[c] = 0.0
                eliminated_count += 1
                if c not in self.contradicting_answers:
                    self.contradicting_answers[c] = []
                self.contradicting_answers[c].append(f"Q: '{question}' -> A: {ans_clean}")
            else:
                new_active.append(c)
                if c not in self.supporting_answers:
                    self.supporting_answers[c] = []
                self.supporting_answers[c].append(f"Q: '{question}' -> A: {ans_clean}")

        # Safety: If all were eliminated or none were eliminated, don't use this partition
        if not new_active or eliminated_count == 0:
            for c in active_list:
                if c in self.contradicting_answers and self.contradicting_answers[c] and self.contradicting_answers[c][-1] == f"Q: '{question}' -> A: {ans_clean}":
                    self.contradicting_answers[c].pop()
                    self.candidates[c] = 1.0 / len(active_list)
                    self.elimination_history.pop(c, None)
                if c in self.supporting_answers and self.supporting_answers[c] and self.supporting_answers[c][-1] == f"Q: '{question}' -> A: {ans_clean}":
                    self.supporting_answers[c].pop()
            return False

        # Normalize remaining active candidates
        sum_prob = sum(self.candidates[c] for c in new_active)
        if sum_prob > 0.0:
            for c in new_active:
                self.candidates[c] /= sum_prob
        else:
            equal_prob = 1.0 / len(new_active)
            for c in new_active:
                self.candidates[c] = equal_prob

        top_candidate = max(new_active, key=lambda c: self.candidates[c])
        logger.info(
            f"[bold green]⚡ [INSTANT 0ms PARTITION] Eliminated {eliminated_count} candidates! "
            f"{len(new_active)} remaining. Top: '{top_candidate}' ({self.candidates[top_candidate]:.1%})[/bold green]"
        )
        return True

    async def update_probabilities(self, question: str, answer: str) -> None:
        """Prunes candidates by asking the LLM to identify contradictions in batch."""
        active_list = self.get_active_candidates()
        if not active_list:
            return

        logger.info(f"Evaluating consistency of {len(active_list)} candidates against: Q: '{question}' -> A: {answer}...")

        # Limit candidates sent to LLM to prevent token blowup
        eval_sample = active_list[:40]
        
        # Formulate LLM prompt to identify contradictions in batch
        system_prompt = (
            "You are the Candidate Consistency Evaluator of an autonomous Agent Grand Prix racing agent.\n"
            "Your job is to identify which candidate entities are INCONSISTENT with a specific question and answer pair.\n"
            "An entity is inconsistent if it contradicts the known fact.\n"
            "Examples:\n"
            "- Question: 'Is it a country in Asia?' -> Answer: 'YES'. Inconsistent entity: 'Germany' (Germany is in Europe).\n"
            "- Question: 'Is it a mammal?' -> Answer: 'NO'. Inconsistent entity: 'Lion' (Lion is a mammal).\n"
            "Be CONSERVATIVE: only eliminate entities you are CERTAIN are inconsistent. If unsure, keep the entity.\n"
            "Output a JSON array of strings containing ONLY the entities from the provided list that are INCONSISTENT and must be eliminated.\n"
            "Only output the JSON array. Do not include explanation."
        )
        
        user_prompt = (
            f"Question: '{question}'\n"
            f"Answer: '{answer}'\n"
            f"Candidates: {json.dumps(eval_sample)}\n"
            "List all inconsistent entities from the candidates list:"
        )

        eliminated_set: Set[str] = set()
        try:
            response_text = await self.provider.generate_response(system_prompt, user_prompt)
            
            from agp.json_utils import clean_and_parse_json
            eliminated = clean_and_parse_json(response_text)
            if isinstance(eliminated, list):
                eliminated_set = {str(item).strip().lower() for item in eliminated}
            else:
                logger.warning(f"LLM returned non-list for elimination: {type(eliminated)}. Skipping pruning.")
        except Exception as e:
            logger.warning(f"Batch candidate pruning failed: {e}. No candidates eliminated this round.")
            # On LLM failure, don't eliminate anything - just track the Q&A
            for c in active_list:
                if c not in self.supporting_answers:
                    self.supporting_answers[c] = []
                self.supporting_answers[c].append(f"Q: '{question}' -> A: {answer}")
            return

        # Perform pruning
        reason = f"Contradicts: Q: '{question}' -> A: {answer}"
        new_active = []
        eliminated_count = 0
        
        for c in active_list:
            c_lower = c.lower()
            if c_lower in eliminated_set:
                self.elimination_history[c] = reason
                self.candidates[c] = 0.0
                eliminated_count += 1
                if c not in self.contradicting_answers:
                    self.contradicting_answers[c] = []
                self.contradicting_answers[c].append(f"Q: '{question}' -> A: {answer}")
            else:
                new_active.append(c)
                if c not in self.supporting_answers:
                    self.supporting_answers[c] = []
                self.supporting_answers[c].append(f"Q: '{question}' -> A: {answer}")

        # BUG FIX: If ALL candidates were eliminated, this is likely an LLM error.
        # Instead of resetting everything (losing all evidence), restore the top 5 candidates
        # with reduced probability and keep all historical evidence intact.
        if not new_active and active_list:
            logger.warning(
                f"[orange3]LLM eliminated ALL {len(active_list)} candidates! "
                f"This is likely an error. Restoring top 5 with reduced confidence.[/orange3]"
            )
            # Restore top 5 from the original list (sorted by how many supporting answers they have)
            restore_candidates = sorted(
                active_list, 
                key=lambda c: len(self.supporting_answers.get(c, [])), 
                reverse=True
            )[:5]
            equal_prob = 1.0 / len(restore_candidates)
            for c in restore_candidates:
                self.candidates[c] = equal_prob
                # Remove from elimination history since we're restoring them
                self.elimination_history.pop(c, None)
            new_active = restore_candidates
            logger.info(f"Restored {len(restore_candidates)} candidates: {restore_candidates}")

        # Normalize remaining probabilities
        if new_active:
            sum_prob = sum(self.candidates[c] for c in new_active)
            if sum_prob > 0.0:
                for c in new_active:
                    self.candidates[c] /= sum_prob
            else:
                # Fallback to equal probability
                equal_prob = 1.0 / len(new_active)
                for c in new_active:
                    self.candidates[c] = equal_prob
            
            top_candidate = max(new_active, key=lambda c: self.candidates[c])
            logger.info(
                f"Pruning complete. Eliminated {eliminated_count}. {len(new_active)} candidates remaining. "
                f"Top candidate: '{top_candidate}' (Conf: {self.candidates[top_candidate]:.2%})"
            )

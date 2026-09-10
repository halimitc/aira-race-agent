import json
from typing import List, Dict
from logger import logger
from prompts import SYSTEM_QUESTION_GENERATION, USER_QUESTION_GEN_TEMPLATE
from agp.reasoning_provider import ReasoningProvider

class QuestionGenerator:
    """Generates candidate yes/no questions to divide the search space efficiently."""
    
    def __init__(self, provider: ReasoningProvider):
        self.provider = provider

    async def generate_questions(
        self, hint: str, history: List[Dict[str, str]], active_candidates: List[str]
    ) -> List[str]:
        """Formulates a list of YES/NO questions designed to split the candidate set."""
        if not active_candidates:
            return []

        # If we have only 1 candidate left, no questions are needed
        if len(active_candidates) <= 1:
            return []

        # Format history string
        formatted_history = ""
        for h in history:
            formatted_history += f"Q: {h['question']} -> Answer: {h['answer']}\n"
        if not formatted_history:
            formatted_history = "None"

        # Limit candidate count in prompt to prevent token blowup
        candidate_sample = active_candidates[:20]
        if len(active_candidates) > 20:
            candidates_str = f"{json.dumps(candidate_sample)} ... and {len(active_candidates) - 20} more"
        else:
            candidates_str = json.dumps(candidate_sample)

        user_prompt = USER_QUESTION_GEN_TEMPLATE.format(
            hint=hint,
            history=formatted_history,
            candidates=candidates_str
        )

        try:
            logger.info("Generating candidate questions using LLM...")
            response_text = await self.provider.generate_response(
                SYSTEM_QUESTION_GENERATION, user_prompt
            )
            
            # Parse JSON list response safely
            from agp.json_utils import clean_and_parse_json
            questions = clean_and_parse_json(response_text)
            if not isinstance(questions, list):
                questions = [str(questions)]
            
            # Clean and filter duplicates/invalid questions
            cleaned_questions = []
            seen_history = {h["question"].strip().lower() for h in history}
            
            for q in questions:
                q_clean = q.strip()
                if not q_clean:
                    continue
                q_lower = q_clean.lower()
                
                # Check for history duplicates
                if q_lower in seen_history:
                    continue
                    
                # Ensure it is phrased as a question
                if not q_clean.endswith("?"):
                    q_clean += "?"
                    
                cleaned_questions.append(q_clean)
                
            logger.info(f"Generated {len(cleaned_questions)} unique candidate questions.")
            return cleaned_questions
            
        except Exception as e:
            logger.error(f"Failed to generate questions: {e}")
            # Fallback questions
            return [
                f"Is it located in or associated with North America?",
                f"Is it a living organism?",
                f"Was it created or discovered before the 20th century?"
            ]

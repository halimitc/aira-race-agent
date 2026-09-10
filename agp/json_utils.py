import re
import json
from typing import Any

def clean_and_parse_json(text: str) -> Any:
    """
    Robustly extracts and parses JSON from raw LLM responses.
    Handles:
    - <think>...</think> reasoning tags
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Preamble/conversational text ("Here are the questions: ...")
    - Trailing commentary or explanations
    """
    if not text:
        raise ValueError("Empty response text received from LLM.")
    
    # 1. Remove <think>...</think> tags if present
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    
    # 2. Extract content from markdown code fence if present
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

    # 3. Direct parse attempt
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 4. Bracket search fallback: find first '[' or '{' and matching closing bracket
    start_bracket = -1
    for i, char in enumerate(cleaned):
        if char in ('[', '{'):
            start_bracket = i
            break
            
    if start_bracket != -1:
        target_char = ']' if cleaned[start_bracket] == '[' else '}'
        end_bracket = cleaned.rfind(target_char)
        if end_bracket != -1 and end_bracket > start_bracket:
            sub = cleaned[start_bracket:end_bracket + 1]
            try:
                return json.loads(sub)
            except Exception:
                pass

    # 5. Regex rescue for Single-Pass Fusion object
    if "best_question" in cleaned:
        q_match = re.search(r'"best_question"\s*:\s*"([^"\r\n]+)', cleaned)
        if q_match:
            best_q = q_match.group(1).strip()
            yes_match = re.search(r'"yes_candidates"\s*:\s*\[(.*?)\]', cleaned, re.DOTALL)
            no_match = re.search(r'"no_candidates"\s*:\s*\[(.*?)\]', cleaned, re.DOTALL)
            yes_cands = [x.strip(' "\'') for x in yes_match.group(1).split(',') if x.strip(' "\'')] if yes_match else []
            no_cands = [x.strip(' "\'') for x in no_match.group(1).split(',') if x.strip(' "\'')] if no_match else []
            return {
                "best_question": best_q,
                "reasoning": "regex recovered",
                "yes_candidates": yes_cands,
                "no_candidates": no_cands
            }

    # 6. Regex rescue for list of strings (e.g. candidate pruning)
    items = re.findall(r'"([^"\\]+)"', cleaned)
    if items:
        return items

    # 7. Last resort: raise original error
    return json.loads(cleaned)

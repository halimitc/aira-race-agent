import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import config
from logger import logger

class LearningEngine:
    """Maintains a historical database of question effectiveness per category."""
    
    def __init__(self, filepath: Optional[Path] = None):
        self.filepath = filepath or config.learning_file
        self.database: Dict[str, Any] = self._load_database()

    def _load_database(self) -> Dict[str, Any]:
        """Loads historical question records from JSON database."""
        default_db = {"categories": {}, "races": [], "solutions": {}}
        if not self.filepath.exists():
            return default_db
            
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    if "categories" not in data:
                        data["categories"] = {}
                    if "races" not in data:
                        data["races"] = []
                    if "solutions" not in data:
                        data["solutions"] = {}
                    return data
        except Exception as e:
            logger.error(f"Error loading learning database: {e}")
        return default_db

    def _save_database(self) -> None:
        """Saves current learning database to JSON file using atomic write."""
        try:
            tmp_path = self.filepath.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.database, f, ensure_ascii=False, indent=2)
            import os
            os.replace(str(tmp_path), str(self.filepath))
        except Exception as e:
            logger.error(f"Failed to write learning database: {e}")

    def _get_category_key(self, hint: str) -> str:
        """Determines a normalized category key from the raw hint text."""
        hint_lower = hint.lower().strip()
        
        # Categorize common keywords — aligned with knowledge_base.py categories
        category_keywords = {
            "country": ["country", "nation", "republic", "kingdom"],
            "animal": ["animal", "mammal", "creature", "bird", "fish", "insect", "reptile"],
            "movie": ["movie", "film", "cinema"],
            "book": ["book", "novel", "literature", "story"],
            "person": ["person", "actor", "writer", "president", "leader", "celebrity", "politician"],
            "fruit": ["fruit"],
            "planet": ["planet", "solar system", "celestial"],
            "city": ["city", "capital", "metropolis", "town"],
            "song": ["song", "track", "single", "hit"],
            "music": ["music", "band", "artist", "musician", "singer"],
            "sport": ["sport", "game", "athletic"],
            "food": ["food", "dish", "cuisine", "meal", "recipe"],
            "brand": ["brand", "trademark"],
            "company": ["company", "corporation", "business", "startup", "tech company"],
            "color": ["color", "colour", "shade", "hue"],
            "element": ["element", "chemical", "atom", "periodic"],
            "language": ["language", "tongue", "dialect"],
            "instrument": ["instrument", "musical instrument"],
            "river": ["river", "stream", "waterway"],
            "mountain": ["mountain", "peak", "summit", "volcano"],
            "ocean": ["ocean", "sea", "body of water"],
            "continent": ["continent"],
            "tv_show": ["tv show", "television", "series", "sitcom", "drama series"],
            "video_game": ["video game", "game", "gaming"],
            "invention": ["invention", "discovery", "technology"],
            "currency": ["currency", "money", "coin"],
            "holiday": ["holiday", "festival", "celebration"],
            "dessert": ["dessert", "sweet", "pastry", "cake"],
            "flower": ["flower", "plant", "bloom", "blossom"],
            "gemstone": ["gemstone", "gem", "jewel", "stone", "crystal"],
            "dance": ["dance", "dancing"],
            "mythology": ["mythology", "myth", "god", "goddess", "deity"],
            "landmark": ["landmark", "monument", "wonder", "building", "structure"],
            "dinosaur": ["dinosaur", "prehistoric"],
            "constellation": ["constellation", "star", "zodiac"],
            "board_game": ["board game", "card game", "tabletop"],
            "musical": ["musical", "broadway", "theatre", "theater"],
            "programming_language": ["programming", "coding", "software"],
            "car": ["car", "automobile", "vehicle"],
            "scientist": ["scientist", "physicist", "chemist", "biologist", "researcher"],
            "superhero": ["superhero", "comic", "marvel", "dc"],
        }
        
        for category, keywords in category_keywords.items():
            if any(kw in hint_lower for kw in keywords):
                return category
        
        # Strip common filler prefixes to prevent category collisions on "it's_a"
        clean_hint = hint_lower
        for prefix in ["it's a ", "it is a ", "it's ", "it is ", "a ", "an ", "the "]:
            if clean_hint.startswith(prefix):
                clean_hint = clean_hint[len(prefix):].strip()
                break
        
        # Default fallback is the first two words of the cleaned hint
        words = clean_hint.split()
        return "_".join(words[:2]) if len(words) >= 2 else clean_hint

    def get_best_questions(self, hint: str, limit: int = 3) -> List[str]:
        """Retrieves historically high-information questions for the hint category."""
        category = self._get_category_key(hint)
        category_data = self.database["categories"].get(category, {})
        if not category_data:
            return []

        # Sort questions by average information gain
        # Format of category_data: {question: {"info_gains": [0.8, 0.9], "avg_gain": 0.85, "usage_count": 2}}
        sorted_qs = sorted(
            category_data.keys(),
            key=lambda q: category_data[q].get("avg_gain", 0.0),
            reverse=True
        )
        
        best = sorted_qs[:limit]
        logger.info(f"Question Memory: Retrieved {len(best)} top questions for category '{category}'")
        return best

    def record_question_effectiveness(self, hint: str, question: str, info_gain: float) -> None:
        """Logs the performance of a single question under its hint category."""
        category = self._get_category_key(hint)
        
        if category not in self.database["categories"]:
            self.database["categories"][category] = {}
            
        category_data = self.database["categories"][category]
        
        if question not in category_data:
            category_data[question] = {
                "info_gains": [],
                "avg_gain": 0.0,
                "usage_count": 0
            }
            
        q_record = category_data[question]
        q_record["info_gains"].append(info_gain)
        # ISU-4: Limit to last 20 entries to prevent unbounded growth
        if len(q_record["info_gains"]) > 20:
            q_record["info_gains"] = q_record["info_gains"][-20:]
        q_record["usage_count"] += 1
        q_record["avg_gain"] = sum(q_record["info_gains"]) / len(q_record["info_gains"])
        
        self._save_database()

    def record_race_results(self, race_summary: Dict[str, Any]) -> None:
        """Stores general metrics of a finished race for future analysis."""
        self.database["races"].append(race_summary)
        self._save_database()
        logger.info("[green]Recorded race results in learning database.[/green]")

    def record_solution(self, hint: str, solution: str) -> None:
        """Records the correct answer for a hint so it can be instantly solved in future races."""
        if "solutions" not in self.database:
            self.database["solutions"] = {}
        # Normalize hint key
        hint_key = hint.strip().lower()
        self.database["solutions"][hint_key] = solution.strip()
        self._save_database()
        logger.info(f"[green]Saved solution mapping: '{hint}' -> '{solution}'[/green]")

    def get_known_solution(self, hint: str) -> Optional[str]:
        """Returns a previously solved answer for this hint, or None if unknown."""
        solutions = self.database.get("solutions", {})
        hint_key = hint.strip().lower()
        return solutions.get(hint_key)


from typing import List, Dict, Any
from logger import logger

class TrackAnalyzer:
    """Analyzes track characteristics and rates difficulty, cost, and competitor presence."""
    
    def __init__(self):
        pass

    def analyze_track(self, track: Dict[str, Any]) -> Dict[str, Any]:
        """Calculates complexity, estimated cost, and starting delays for a single track."""
        points = track.get("points", [])
        point_count = len(points) if isinstance(points, list) else 5  # Default estimation
        
        # Difficulty rating based on point count
        if point_count <= 3:
            difficulty = "Easy"
            est_cost_usdc = point_count * 0.005  # ~5 questions per point
        elif point_count <= 7:
            difficulty = "Medium"
            est_cost_usdc = point_count * 0.007
        else:
            difficulty = "Hard"
            est_cost_usdc = point_count * 0.010
            
        analysis = {
            "track_id": track.get("id"),
            "name": track.get("name"),
            "points_count": point_count,
            "difficulty": difficulty,
            "estimated_cost_usdc": est_cost_usdc,
            "starts_in_seconds": int(track.get("startsInSeconds") or 0),
            "status": track.get("status", "unknown")
        }
        
        logger.info(
            f"Track Analysis - Name: {analysis['name']} | "
            f"Points: {analysis['points_count']} ({analysis['difficulty']}) | "
            f"Est. Cost: {analysis['estimated_cost_usdc']:.3f} AGP"
        )
        return analysis

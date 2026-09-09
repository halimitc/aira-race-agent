import time
from typing import List, Dict, Any, Optional
from logger import logger

class RaceStrategy:
    """Manages high-level decisions such as track selection and fallback strategies."""
    
    def __init__(self):
        pass

    def choose_best_track(self, tracks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Selects the best track to race on based on start times, activity status, and length."""
        if not tracks:
            return None

        # Filter out tracks that have already ended, timed out, or finished
        open_tracks = []
        for track in tracks:
            phase = str(track.get("phase", "")).lower()
            status = str(track.get("status", "")).lower()
            is_over = (
                track.get("over") is True 
                or track.get("timedOut") is True 
                or track.get("finished") is True 
                or phase == "over"
                or status in ("abandoned", "finished", "completed")
            )
            if not is_over:
                open_tracks.append(track)

        if not open_tracks:
            logger.warning("[yellow]No open/active race tracks currently available on server. All listed tracks have ended.[/yellow]")
            return None

        # Separate into registration, betting, active, and upcoming tracks
        registration_tracks = []
        betting_tracks = []
        active_tracks = []
        upcoming_tracks = []

        for track in open_tracks:
            phase = str(track.get("phase", "")).lower()
            status = str(track.get("status", "")).lower()
            starts_in = int(track.get("startsInSeconds") or 0)
            
            if phase == "registration" or (track.get("registrationClosesAt") and not track.get("started")):
                registration_tracks.append(track)
            elif phase == "betting" or (track.get("bettingOpensAt") and not track.get("started")):
                betting_tracks.append(track)
            elif phase in ("racing", "active") or status == "active" or (track.get("started") and starts_in == 0):
                active_tracks.append(track)
            elif starts_in > 0 or phase == "upcoming":
                upcoming_tracks.append(track)
            else:
                active_tracks.append(track)

        # Priority 1: Tracks currently open for registration (time-critical 30m window!)
        if registration_tracks:
            registration_tracks.sort(key=lambda t: int(t.get("startsInSeconds") or 999999))
            selected = registration_tracks[0]
            logger.info(
                f"[bold green]Selected track in REGISTRATION phase:[/bold green] '{selected.get('name')}' (ID: {selected.get('id')})"
            )
            return selected

        # Priority 2: Active racing tracks
        if active_tracks:
            # Choose the one with the fewest points (easiest to finish first)
            active_tracks.sort(key=lambda t: len(t.get("points", [])) if isinstance(t.get("points"), list) else 99)
            selected = active_tracks[0]
            logger.info(f"Selected active track: '{selected.get('name')}' (ID: {selected.get('id')})")
            return selected

        # Priority 3: Tracks in betting phase or upcoming
        candidate_pool = betting_tracks or upcoming_tracks
        if candidate_pool:
            candidate_pool.sort(key=lambda t: int(t.get("startsInSeconds") or 999999))
            selected = candidate_pool[0]
            phase_label = selected.get("phase", "upcoming").upper()
            logger.info(
                f"Selected {phase_label} track: '{selected.get('name')}' (ID: {selected.get('id')}) "
                f"starting in {selected.get('startsInSeconds')}s"
            )
            return selected

        # Fallback to the first open track
        logger.info(f"Fallback to first open track: '{open_tracks[0].get('name')}'")
        return open_tracks[0]

    def get_fallback_guesses(self, top_candidates: List[str], guess_cost_usdc: float = 0.0) -> List[str]:
        """Returns a list of alternative names/guesses to submit in sequence when the primary guess fails."""
        # If guesses are paid, do not submit fallbacks to avoid wasting USDC
        if guess_cost_usdc > 0:
            return []
        # If we have multiple candidates with relatively close probabilities, we can guess the top 3
        # since guesses are free and have no cooldown/penalty
        return top_candidates[:3]


import asyncio
import time
from typing import Optional, Dict, Any, List
from config import config
from logger import logger
from agp.client import AGPMCPClient
from agp.oracle import OracleGateway, UnsafeBalanceError
from agp.reasoning_provider import ReasoningProvider
from agp.knowledge_base import HybridKnowledgeBase
from agp.candidate_manager import CandidateManager
from agp.question_generator import QuestionGenerator
from agp.entropy import EntropyEngine
from agp.cost_optimizer import CostOptimizer
from agp.strategy import RaceStrategy
from agp.canonical_resolver import CanonicalResolver
from agp.memory import RaceMemory
from agp.learning import LearningEngine
from agp.metrics import RaceMetrics
from agp.track_analyzer import TrackAnalyzer

# Maximum seconds for race before forcing ultra-aggressive guessing
DEADLINE_URGENCY_THRESHOLD = 120  # last 2 minutes = panic mode

class RacePlanner:
    """Core autonomous orchestrator that drives the agent through AGP races."""
    
    def __init__(self, client: AGPMCPClient):
        self.client = client
        self.provider = ReasoningProvider()
        
        # Sub-component injection
        self.oracle = OracleGateway(client)
        self.kb = HybridKnowledgeBase(self.provider)
        self.candidate_manager = CandidateManager(self.provider)
        self.question_generator = QuestionGenerator(self.provider)
        self.entropy_engine = EntropyEngine(self.provider)
        self.cost_optimizer = CostOptimizer()
        self.strategy = RaceStrategy()
        self.resolver = CanonicalResolver(self.provider)
        self.memory = RaceMemory()
        self.learning = LearningEngine()
        self.metrics = RaceMetrics()
        self.analyzer = TrackAnalyzer()

    def _extract_run_info(self, state: Any) -> Optional[Dict[str, Any]]:
        """Extracts run details supporting both wrapped and flat structures."""
        if not isinstance(state, dict):
            return None
        # If 'run' key exists, it takes precedence
        if "run" in state:
            if isinstance(state["run"], dict):
                return state["run"]
            return None  # If 'run' is present but is None/null, there is no active run
        # If it's a flat structure with trackId, it's the run itself
        if "trackId" in state:
            return state
        return None

    def _extract_current_point(self, run_info: Dict[str, Any]) -> int:
        """Extracts current point index supporting idx, currentPoint, and currentCheckpoint."""
        for key in ("idx", "currentPoint", "currentCheckpoint"):
            val = run_info.get(key)
            if val is not None:
                try:
                    return int(val)
                except (ValueError, TypeError):
                    continue
        return 0

    async def execute_race_loop(self, track_id: Optional[str] = None) -> None:
        """Starts or resumes a race on the specified track and runs the main loop until finished."""
        # 1. Start Client (guard against double-start from app.py)
        if not self.client.is_running:
            await self.client.start()
        self.metrics.start_race()
        self.race_deadline: Optional[float] = None  # Unix timestamp when race ends

        # BUG FIX 10: Load previous memory state for crash recovery
        if self.memory.load():
            logger.info(f"[green]Resumed from saved state: checkpoint {self.memory.state['current_point']}[/green]")

        # 2. Check Sigil Balance
        try:
            await self.oracle.check_balance()
        except UnsafeBalanceError as e:
            logger.error(f"[red]Cannot start race: {e}[/red]")
            return

        # 3. Check current race state (Resume Recovery)
        logger.info("Checking current race state...")
        race_state = await self.client.my_race()
        
        # Extract run info and filter abandoned/finished status
        run_data = self._extract_run_info(race_state)
        if run_data:
            status_str = str(run_data.get("status", "")).lower()
            if status_str in ("abandoned", "finished", "completed") or run_data.get("finished"):
                logger.warning(f"[yellow]Saved track state is '{status_str}'. Resetting memory to select an active track...[/yellow]")
                self.memory.reset()
                run_data = None

        if not run_data:
            queued_info = race_state.get("queued") if isinstance(race_state, dict) else None
            if queued_info and isinstance(queued_info, dict) and queued_info.get("trackId"):
                queued_track = queued_info["trackId"]
                logger.info(f"[bold green]Already registered on grid: {queued_info.get('trackName', queued_track)} (Position #{queued_info.get('position')})[/bold green]")
                if not track_id:
                    track_id = queued_track

            tracks = await self.client.list_tracks()
            if not track_id:
                logger.info("No active race and no track_id provided. Retrieving tracks list...")
                best_track = self.strategy.choose_best_track(tracks)
                if not best_track:
                    logger.error("[red]No tracks available to race on.[/red]")
                    return
                track_id = best_track["id"]
            
            logger.info(f"Starting track: {track_id}")
            try:
                start_response = await self.client.start_track(track_id)
                logger.info(f"Registered on track successfully: {start_response}")
            except Exception as start_err:
                err_msg = str(start_err)
                if "ended" in err_msg.lower() or "over" in err_msg.lower():
                    logger.warning(f"[yellow]Track '{track_id}' has ended on the server ({err_msg}). No active live race is currently running.[/yellow]")
                    return
                raise start_err
            
            # Check if start_response is marked abandoned/finished
            if isinstance(start_response, dict):
                resp_status = str(start_response.get("status", "")).lower()
                if resp_status in ("abandoned", "finished", "completed") or start_response.get("finished"):
                    logger.warning(f"[yellow]Track '{track_id}' is marked as '{resp_status}'. Resetting memory and trying next available track...[/yellow]")
                    self.memory.reset()
                    valid_tracks = [t for t in tracks if t.get("id") != track_id and str(t.get("status", "")).lower() not in ("abandoned", "finished", "completed")]
                    best_track = self.strategy.choose_best_track(valid_tracks) if valid_tracks else None
                    if best_track:
                        track_id = best_track["id"]
                        logger.info(f"Retrying with active track: {track_id}")
                        try:
                            start_response = await self.client.start_track(track_id)
                        except Exception as retry_err:
                            logger.warning(f"[yellow]Retried track '{track_id}' has ended: {retry_err}[/yellow]")
                            return
                    else:
                        logger.warning("[yellow]No open/active race tracks currently available on server. Waiting for the next live race event...[/yellow]")
                        return

            # Fetch updated race state
            race_state = await self.client.my_race()
            run_data = self._extract_run_info(race_state)
            if not run_data and isinstance(start_response, dict) and "trackId" in start_response:
                resp_status = str(start_response.get("status", "")).lower()
                if resp_status not in ("abandoned", "finished", "completed") and not start_response.get("finished"):
                    run_data = self._extract_run_info(start_response)
                
            # If run_data is not yet populated, check if we are queued or registered for an upcoming track (e.g. Predict race registration / betting phase)
            if not run_data and track_id:
                logger.info(f"[bold cyan]Agent registered for track '{track_id}'. Waiting for grid seating and race start...[/bold cyan]")
                
                last_log_time = 0.0
                while self.client.is_running and not run_data:
                    await asyncio.sleep(8.0)
                    try:
                        race_state = await self.client.my_race()
                        run_data = self._extract_run_info(race_state)
                        if run_data:
                            logger.info(f"[bold green]🏁 Grid locked and run active! Run ID: {run_data.get('id')}[/bold green]")
                            break
                        
                        # Inspect list_tracks to provide live countdown and phase info
                        now = time.time()
                        if (now - last_log_time) >= 16.0:
                            last_log_time = now
                            tracks = await self.client.list_tracks()
                            matched_track = next((t for t in tracks if t.get("id") == track_id), None)
                            
                            if matched_track:
                                phase = str(matched_track.get("phase", "UPCOMING")).upper()
                                starts_in = matched_track.get("startsInSeconds")
                                racers = matched_track.get("racerCount", 0)
                                queued = matched_track.get("queuedCount", 0)
                                
                                countdown_str = ""
                                if starts_in is not None and int(starts_in) > 0:
                                    mins, secs = divmod(int(starts_in), 60)
                                    countdown_str = f" | Starts in: {mins}m {secs:02d}s"
                                
                                queue_msg = race_state.get("message", "") if isinstance(race_state, dict) else ""
                                logger.info(
                                    f"[cyan][Staging Grid][/cyan] Track: {matched_track.get('name', track_id[:10])} | "
                                    f"Phase: [bold yellow]{phase}[/bold yellow] | "
                                    f"Racers: {racers} (Queued: {queued}){countdown_str}"
                                )
                                if queue_msg and "no active race" not in queue_msg.lower():
                                    logger.info(f"[dim]{queue_msg}[/dim]")
                                
                                if matched_track.get("over") or matched_track.get("timedOut") or str(matched_track.get("status", "")).lower() == "over":
                                    logger.warning(f"[yellow]Track '{track_id}' is marked OVER on server.[/yellow]")
                                    return
                    except Exception as poll_err:
                        logger.debug(f"Staging loop poll exception: {poll_err}")

            if not run_data:
                logger.warning("[yellow]No active race run found on server. Ready for the next live race![/yellow]")
                return

        # Current track ID
        active_track_id = run_data.get("trackId")
        logger.info(f"[green]Active Race Run ID: {run_data.get('id')} on Track: {active_track_id}[/green]")
        
        # Load track costs dynamically
        try:
            tracks = await self.client.list_tracks()
            active_track = None
            for t in tracks:
                if t.get("id") == active_track_id:
                    active_track = t
                    break
            
            charge_curr = "AGP"
            ask_cost = 0.001
            guess_cost = 0.000
            spend_cap = None
            time_limit_sec = None
            if active_track:
                charge_curr = active_track.get("chargeCurrency") or "AGP"
                ask_cost = float(active_track.get("questionCostUsd") or 0.001)
                guess_cost = float(active_track.get("guessCostUsd") or 0.000)
                spend_cap_raw = active_track.get("spendCapUsd")
                spend_cap = float(spend_cap_raw) if spend_cap_raw is not None else None
                time_limit_raw = active_track.get("timeLimitSeconds")
                time_limit_sec = int(time_limit_raw) if time_limit_raw is not None else None
            logger.info(f"[cyan]Track pricing loaded -> Ask: {ask_cost:.4f} {charge_curr} | Guess: {guess_cost:.4f} {charge_curr} | SpendCap: {f'{spend_cap:.2f} {charge_curr}' if spend_cap else 'unlimited'} | TimeLimit: {f'{time_limit_sec}s' if time_limit_sec else 'unlimited'}[/cyan]")
            self.cost_optimizer = CostOptimizer(ask_cost_usdc=ask_cost, guess_cost_usdc=guess_cost, spend_cap_usdc=spend_cap, currency=charge_curr)
            
            # P0-3 FIX: Extract actual server-side spend to sync budget tracking on resume
            server_spent = None
            server_remaining = None
            # Try start_response first (freshest data)
            if isinstance(start_response, dict):
                server_spent = start_response.get("spentUsd")
                server_remaining = start_response.get("remainingUsd")
            # Fallback to run_data
            if server_spent is None and isinstance(run_data, dict):
                server_spent = run_data.get("spentUsd")
                server_remaining = run_data.get("remainingUsd")
            # Fallback to active_track data
            if server_spent is None and active_track:
                server_spent = active_track.get("spentUsd")
                server_remaining = active_track.get("remainingUsd")
            
            if server_spent is not None:
                spent_val = float(server_spent)
                self.cost_optimizer.total_spent_usdc = spent_val
                logger.info(f"[cyan]Server budget sync -> Spent: {spent_val:.4f} {charge_curr} | Remaining: {float(server_remaining) if server_remaining is not None else 'N/A'} {charge_curr}[/cyan]")
            elif server_remaining is not None and spend_cap is not None:
                # Infer spent from remaining
                spent_val = spend_cap - float(server_remaining)
                self.cost_optimizer.total_spent_usdc = max(0.0, spent_val)
                logger.info(f"[cyan]Server budget sync (inferred) -> Spent: {max(0.0, spent_val):.4f} {charge_curr}[/cyan]")
            # Set race deadline if time limit exists
            if time_limit_sec:
                starts_at = active_track.get("startsAt", "")
                starts_in_sec = active_track.get("startsInSeconds")
                # BUG FIX 5: Calculate accurate deadline using server timing data
                if starts_in_sec is not None and int(starts_in_sec) > 0:
                    # Race hasn't started yet — deadline = now + startsInSeconds + timeLimit
                    self.race_deadline = time.time() + int(starts_in_sec) + time_limit_sec
                    logger.info(f"[yellow]Race deadline set: starts in {starts_in_sec}s + {time_limit_sec}s limit[/yellow]")
                elif starts_at:
                    # Try to parse ISO timestamp to compute elapsed time
                    try:
                        from datetime import datetime, timezone
                        start_dt = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
                        elapsed = (datetime.now(timezone.utc) - start_dt).total_seconds()
                        remaining = max(0, time_limit_sec - elapsed)
                        self.race_deadline = time.time() + remaining
                        logger.info(f"[yellow]Race deadline set: {remaining:.0f}s remaining (elapsed: {elapsed:.0f}s)[/yellow]")
                    except Exception:
                        self.race_deadline = time.time() + time_limit_sec
                        logger.info(f"[yellow]Race deadline set (fallback): {time_limit_sec}s from now[/yellow]")
                else:
                    # No timing info — conservative fallback
                    self.race_deadline = time.time() + time_limit_sec
                    logger.info(f"[yellow]Race deadline set (fallback): {time_limit_sec}s from now[/yellow]")
        except Exception as cost_err:
            logger.warning(f"Failed to load track pricing details: {cost_err}. Using defaults.")
            self.cost_optimizer = CostOptimizer(ask_cost_usdc=0.001, guess_cost_usdc=0.0)

        # Store initial track details in memory
        self.memory.state["track_id"] = active_track_id
        self.memory.state["start_time"] = time.time()
        self.memory.state["status"] = "racing"
        self.memory.save()

        # Main loop
        # BUG FIX: Initialize from memory to prevent state wipe on crash recovery
        checkpoint_active = self.memory.state.get("current_point", -1)
        # BUG FIX 11: Cache the last race_state to avoid double API calls
        cached_race_state = None
        cached_race_state_time = 0.0
        
        while self.client.is_running:
            try:
                # 4. Read state progress
                # BUG FIX 11: Use my_race() as single source of truth instead of calling both track_state() and my_race()
                now = time.time()
                if cached_race_state is None or (now - cached_race_state_time) > 2.0:
                    cached_race_state = await self.client.my_race()
                    cached_race_state_time = now
                
                race_data = cached_race_state
                run_info = self._extract_run_info(race_data)
                
                if not run_info:
                    logger.warning("No active run data in my_race(). Retrying in 3s...")
                    cached_race_state = None
                    await asyncio.sleep(3.0)
                    continue
                
                # Check for race completion
                is_finished = run_info.get("finished", False) or run_info.get("isFinished", False)
                
                # Check for startsInSeconds (race hasn't started yet)
                starts_in = int(race_data.get("startsInSeconds") or run_info.get("startsInSeconds") or 0)
                if starts_in > 0:
                    phase = str(race_data.get("phase") or run_info.get("phase") or "PREDICT / BETTING").upper()
                    mins, secs = divmod(starts_in, 60)
                    time_str = f"{mins}m {secs:02d}s" if mins > 0 else f"{secs}s"
                    logger.info(f"[bold yellow][{phase}][/bold yellow] Waiting for green flag: {time_str} remaining...")
                    await asyncio.sleep(min(10.0, starts_in))
                    cached_race_state = None  # Force refresh after wait
                    continue

                if is_finished:
                    logger.info(f"[bold green]>>> FINISHED THE RACE! <<<[/bold green]")
                    self.memory.state["status"] = "finished"
                    self.memory.save()
                    break

                # BUG FIX 5: Extract hint from run data with multiple key fallbacks
                current_point = self._extract_current_point(run_info)
                
                # Try multiple possible paths for hint/clue data
                hint = ""
                current_point_data = run_info.get("currentPointDetails", {})
                if current_point_data:
                    hint = current_point_data.get("hint", current_point_data.get("clue", current_point_data.get("description", "")))
                
                # Fallback: check top-level hint keys
                if not hint:
                    hint = run_info.get("hint", run_info.get("clue", ""))
                
                # Fallback: check points array
                if not hint:
                    points = run_info.get("points", [])
                    if isinstance(points, list):
                        for p in points:
                            if isinstance(p, dict) and p.get("status") == "ACTIVE":
                                hint = p.get("hint", p.get("clue", ""))
                                if hint:
                                    break
                
                if not hint:
                    # Log the entire run structure for debugging
                    logger.warning(f"Active checkpoint hint is empty. Run data keys: {list(run_info.keys())}")
                    logger.debug(f"Full run data: {run_info}")
                    cached_race_state = None  # Force refresh
                    await asyncio.sleep(2.0)
                    continue

                # Detect checkpoint change (Clean state transition)
                if current_point != checkpoint_active:
                    logger.info(f"\n[bold yellow]--- Entering Checkpoint {current_point} (Hint: '{hint}') ---[/bold yellow]")
                    checkpoint_active = current_point
                    self.memory.state["current_point"] = current_point
                    self.memory.state["hint"] = hint
                    self.memory.state["history"] = []
                    
                    # Clear Oracle answer cache on checkpoint transition
                    self.oracle.clear_cache()
                    
                    # WEAK-08: Check if we've solved this hint before for instant solve
                    known_solution = self.learning.get_known_solution(hint)
                    if known_solution:
                        logger.info(f"[bold green]🧠 INSTANT SOLVE! Known solution for '{hint}': '{known_solution}'[/bold green]")
                        guess_res = await self.client.guess(known_solution)
                        cached_race_state = None
                        if self._is_guess_correct(guess_res):
                            logger.info(f"[bold green]✓ Instant solve CORRECT! Advancing...[/bold green]")
                            self.cost_optimizer.record_spend(self.cost_optimizer.guess_cost_usdc)
                            self.metrics.record_guess(is_correct=True, cost=self.cost_optimizer.guess_cost_usdc)
                            await self._wait_for_checkpoint_advance(current_point)
                            continue
                        else:
                            logger.warning(f"[orange3]Instant solve '{known_solution}' was WRONG (hint may have different secret now). Proceeding normally.[/orange3]")
                    
                    # Generate fresh candidates for new checkpoint
                    candidates = await self.kb.get_candidates(hint, [])
                    self.candidate_manager.set_candidates(candidates)
                    
                    self.memory.state["candidates"] = candidates
                    self.memory.state["candidate_probabilities"] = self.candidate_manager.candidates.copy()
                    self.memory.save()

                    # P1-3 FIX: Immediate First-Guess Strategy (Free guess quick-strike)
                    if self.cost_optimizer.guess_cost_usdc <= 0 and candidates:
                        first_candidate = candidates[0]
                        first_canonical = await self.resolver.resolve(first_candidate)
                        logger.info(f"[bold cyan]⚡ Instant First-Guess Strike: '{first_canonical}' (Free Guess)[/bold cyan]")
                        first_res = await self.client.guess(first_canonical)
                        if self._is_guess_correct(first_res):
                            logger.info(f"[bold green]🎯 FIRST-GUESS STRIKE HIT! Solved checkpoint {current_point} in 50ms: '{first_canonical}'![/bold green]")
                            self.learning.record_solution(hint, first_canonical)
                            self.memory.save()
                            await self._wait_for_checkpoint_advance(current_point)
                            continue
                        else:
                            logger.info(f"[dim]First-guess strike missed ('{first_canonical}'). Eliminating and proceeding normally.[/dim]")
                            self.candidate_manager.candidates[first_candidate] = 0.0

                # Get active candidates list
                active_candidates = self.candidate_manager.get_active_candidates()
                is_desperation = False
                if not active_candidates:
                    logger.warning("Candidate set empty. Regrowing search space via LLM Reasoning Fallback...")
                    candidates = await self.kb.get_candidates(hint, self.memory.state["history"])
                    self.candidate_manager.set_candidates(candidates)
                    active_candidates = self.candidate_manager.get_active_candidates()
                    if not active_candidates:
                        # Fallback list to prevent infinite loop stalls
                        fallback = ["apple", "paris", "einstein", "avatar", "yellow", "football", "sushi", "google", "english", "guitar"]
                        logger.error(f"[red]Unable to generate candidates. Injecting desperation fallback candidates: {fallback}[/red]")
                        self.candidate_manager.set_candidates(fallback)
                        active_candidates = self.candidate_manager.get_active_candidates()
                        is_desperation = True

                # Check deadline urgency — if near deadline, force ultra-aggressive guessing
                is_urgent = False
                if self.race_deadline:
                    remaining_time = self.race_deadline - time.time()
                    if remaining_time < DEADLINE_URGENCY_THRESHOLD:
                        is_urgent = True
                        logger.warning(f"[bold red]⏰ DEADLINE URGENCY! Only {remaining_time:.0f}s remaining! Switching to panic mode.[/bold red]")

                # 5. Hybrid Guess Burst & Cost-Optimized Guessing
                # If guesses are free, we enter rapid-fire Guess Burst mode for up to 30 candidates.
                # CRITICAL RULE FOR AGP PREDICT: If guesses are PAID ($0.01), burst_limit is 0!
                # (Tie-breaker is lowest spend: every wrong guess demotes ranking by 10 positions!)
                burst_limit = 30 if self.cost_optimizer.guess_cost_usdc <= 0 else 0
                if is_urgent and self.cost_optimizer.guess_cost_usdc <= 0:
                    burst_limit = max(burst_limit, 15)

                if burst_limit > 0 and len(active_candidates) <= burst_limit:
                    logger.info(f"\n[bold yellow]⚡ Entering HYBRID GUESS BURST Phase ({len(active_candidates)} candidates left, limit: {burst_limit}) ⚡[/bold yellow]")
                    solved = False
                    consecutive_misses = 0
                    # P2-2 FIX: Batch canonical resolution prior to burst loop
                    canonical_map = await self.resolver.resolve_batch(active_candidates)
                    for candidate in list(active_candidates):
                        if self.candidate_manager.candidates.get(candidate, 0.0) == 0.0:
                            continue
                        
                        # Circuit Breaker: If 5 consecutive guesses miss and candidate space > 10, switch to Ask Cycle
                        if consecutive_misses >= 5 and len(active_candidates) > 10:
                            logger.warning(f"[orange3]⚡ Guess Burst Circuit Breaker triggered after {consecutive_misses} misses! Switching to Ask Cycle for evidence...[/orange3]")
                            break
                            
                        canonical_guess = canonical_map.get(candidate, candidate)
                        cost_label = "paid" if self.cost_optimizer.guess_cost_usdc > 0 else "free"
                        logger.info(f"[cyan]Burst Guess: '{canonical_guess}' (Original: '{candidate}') ({cost_label})[/cyan]")
                        
                        guess_res = await self.client.guess(canonical_guess)
                        cached_race_state = None  # Force refresh
                        
                        is_correct = self._is_guess_correct(guess_res)
                        
                        self.memory.state["guess_count"] = self.memory.state.get("guess_count", 0) + 1
                        self.cost_optimizer.record_spend(self.cost_optimizer.guess_cost_usdc)
                        self.memory.state["usdc_spent"] = self.memory.state.get("usdc_spent", 0.0) + self.cost_optimizer.guess_cost_usdc
                        self.metrics.record_guess(is_correct=is_correct, cost=self.cost_optimizer.guess_cost_usdc)
                        
                        if is_correct:
                            logger.info(f"[bold green]✓ Checkpoint {current_point} solved via Guess Burst: '{canonical_guess}'![/bold green]")
                            # Save solution for future instant solve
                            self.learning.record_solution(hint, canonical_guess)
                            self.memory.save()
                            solved = True
                            await self._wait_for_checkpoint_advance(current_point)
                            break
                        else:
                            consecutive_misses += 1
                            logger.warning(f"[orange3]✗ Wrong Burst Guess: '{canonical_guess}'. Eliminating candidate.[/orange3]")
                            self.candidate_manager.candidates[candidate] = 0.0
                            self.memory.state["candidate_probabilities"] = self.candidate_manager.candidates.copy()
                            self.memory.save()
                            await asyncio.sleep(0.05)
                            
                    if solved:
                        await asyncio.sleep(0.3)
                        continue
                    else:
                        remaining_active = self.candidate_manager.get_active_candidates()
                        if not remaining_active:
                            logger.warning("[orange3]All candidates exhausted. Force regrowing brand new candidates via Layer 2 LLM Reasoning...[/orange3]")
                            candidates = await self.kb.get_candidates(hint, self.memory.state["history"], force_refresh=True, bypass_offline=True)
                            if not candidates:
                                candidates = await self.kb.get_candidates(hint, self.memory.state["history"], force_refresh=True)
                            self.candidate_manager.set_candidates(candidates)
                            self.memory.save()
                            continue
                        # If active candidates remain (e.g. circuit breaker triggered), proceed to Ask Cycle below

                # Refresh active candidates in case Guess Burst eliminated some items
                active_candidates = self.candidate_manager.get_active_candidates()
                if not active_candidates:
                    continue
                top_candidate = active_candidates[0]
                top_prob = self.candidate_manager.candidates[top_candidate]
                sigil_bal = self.oracle.get_cached_balance()

                # In deadline urgency or spendCap exhausted, force guess regardless
                force_guess = (is_urgent and not self.cost_optimizer.can_afford_ask()) or (not self.cost_optimizer.can_afford_ask() and not self.cost_optimizer.can_afford_guess())
                if force_guess or self.cost_optimizer.should_guess(top_prob, len(active_candidates), sigil_bal):
                    canonical_guess = await self.resolver.resolve(top_candidate)
                    
                    # 🎯 SNIPER PRE-VERIFICATION:
                    # If guess is paid ($0.01), ask the Oracle specifically for $0.001 first!
                    # If YES -> 100% guaranteed win on guess #1 (like tiadler)!
                    # If NO  -> eliminates candidate for 1/10th of the price (saves $0.009 & preserves leaderboard rank)!
                    if self.cost_optimizer.guess_cost_usdc > 0 and self.cost_optimizer.can_afford_ask() and top_prob < 0.98:
                        verify_q = f"Is the secret word specifically '{canonical_guess}'?"
                        logger.info(f"[bold cyan]🎯 Sniper Pre-Verification Ask ($0.001): '{verify_q}'[/bold cyan]")
                        v_answer = await self.oracle.ask(verify_q)
                        history_list = self.memory.state["history"]
                        history_list.append({"question": verify_q, "answer": v_answer})
                        self.cost_optimizer.record_spend(self.cost_optimizer.ask_cost_usdc)
                        self.memory.state["usdc_spent"] = self.memory.state.get("usdc_spent", 0.0) + self.cost_optimizer.ask_cost_usdc
                        self.memory.state["question_count"] = self.memory.state.get("question_count", 0) + 1
                        self.memory.save()
                        
                        if v_answer == "no":
                            logger.warning(f"[orange3]🎯 Sniper check eliminated '{canonical_guess}' for only $0.001! (Saved ${self.cost_optimizer.guess_cost_usdc - self.cost_optimizer.ask_cost_usdc:.4f})[/orange3]")
                            self.candidate_manager.candidates[top_candidate] = 0.0
                            self.memory.state["candidate_probabilities"] = self.candidate_manager.candidates.copy()
                            self.memory.save()
                            continue
                        elif v_answer == "yes":
                            logger.info(f"[bold green]🎯 Sniper check CONFIRMED '{canonical_guess}' with 100% certainty! Submitting winning guess...[/bold green]")
                            top_prob = 1.0

                    cost_label = "paid" if self.cost_optimizer.guess_cost_usdc > 0 else "free"
                    logger.info(f"[cyan]Submitting {cost_label} guess: '{canonical_guess}' (Original: '{top_candidate}')[/cyan]")
                    
                    guess_res = await self.client.guess(canonical_guess)
                    cached_race_state = None
                    
                    is_correct = self._is_guess_correct(guess_res)
                    
                    self.memory.state["guess_count"] = self.memory.state.get("guess_count", 0) + 1
                    self.cost_optimizer.record_spend(self.cost_optimizer.guess_cost_usdc)
                    self.memory.state["usdc_spent"] = self.memory.state.get("usdc_spent", 0.0) + self.cost_optimizer.guess_cost_usdc
                    self.metrics.record_guess(is_correct=is_correct, cost=self.cost_optimizer.guess_cost_usdc)
                    
                    if is_correct:
                        logger.info(f"[bold green]>>> Checkpoint {current_point} SOLVED! <<<[/bold green]")
                        self.learning.record_solution(hint, canonical_guess)
                        self.memory.save()
                        await self._wait_for_checkpoint_advance(current_point)
                        continue
                    else:
                        logger.warning(f"[orange3]Wrong Guess: '{canonical_guess}'. Eliminating from candidates.[/orange3]")
                        self.candidate_manager.candidates[top_candidate] = 0.0
                        
                        fallback_guesses = self.strategy.get_fallback_guesses(active_candidates[1:], self.cost_optimizer.guess_cost_usdc)
                        for alt in fallback_guesses:
                            alt_canonical = await self.resolver.resolve(alt)
                            if alt_canonical.lower() == canonical_guess.lower():
                                continue
                            logger.info(f"[cyan]Submitting fallback guess: '{alt_canonical}'[/cyan]")
                            
                            alt_res = await self.client.guess(alt_canonical)
                            cached_race_state = None
                            
                            self.memory.state["guess_count"] = self.memory.state.get("guess_count", 0) + 1
                            self.cost_optimizer.record_spend(self.cost_optimizer.guess_cost_usdc)
                            self.memory.state["usdc_spent"] = self.memory.state.get("usdc_spent", 0.0) + self.cost_optimizer.guess_cost_usdc
                            
                            alt_correct = self._is_guess_correct(alt_res)
                            self.metrics.record_guess(is_correct=alt_correct, cost=self.cost_optimizer.guess_cost_usdc)
                            
                            if alt_correct:
                                logger.info(f"[bold green]>>> Checkpoint {current_point} SOLVED with fallback '{alt_canonical}'! <<<[/bold green]")
                                self.learning.record_solution(hint, alt_canonical)
                                await self._wait_for_checkpoint_advance(current_point)
                                break
                            else:
                                if alt in self.candidate_manager.candidates:
                                    self.candidate_manager.candidates[alt] = 0.0
                                
                        self.memory.state["candidate_probabilities"] = self.candidate_manager.candidates.copy()
                        self.memory.save()
                        continue

                # 6. Optimized Question Generation & Entropy Selection
                # Primary: Fast Single-Pass Fusion (1 LLM call)
                history_list = self.memory.state["history"]
                best_q = None
                score = {"info_gain": 0.0}
                
                try:
                    best_q, score = await self.entropy_engine.select_best_question_fused(
                        hint, history_list, active_candidates, fallback_questions=None
                    )
                except Exception as fusion_err:
                    logger.warning(f"[yellow]Single-Pass Fusion unavailable ({fusion_err}). Invoking QuestionGenerator fallback...[/yellow]")
                    memory_questions = self.learning.get_best_questions(hint)
                    new_questions = await self.question_generator.generate_questions(hint, history_list, active_candidates)
                    q_pool = list(set(memory_questions + new_questions))
                    asked_qs = {h["question"].strip().lower() for h in history_list}
                    q_pool = [q for q in q_pool if q.strip().lower() not in asked_qs]
                    
                    if q_pool:
                        best_q, score = await self.entropy_engine.select_best_question(q_pool, active_candidates)
                    else:
                        best_q = None

                if not best_q:
                    canonical_guess = await self.resolver.resolve(top_candidate)
                    if self.cost_optimizer.guess_cost_usdc > 0 and self.cost_optimizer.can_afford_ask():
                        best_q = f"Is the secret word specifically '{canonical_guess}'?"
                        logger.info(f"[bold cyan]🎯 Formed specific candidate question ($0.001): '{best_q}'[/bold cyan]")
                    else:
                        logger.warning(f"No unique questions can be generated. Submitting desperation guess: '{canonical_guess}'")
                        guess_res = await self.client.guess(canonical_guess)
                        cached_race_state = None
                        
                        is_correct = self._is_guess_correct(guess_res)
                        self.memory.state["guess_count"] = self.memory.state.get("guess_count", 0) + 1
                        self.memory.state["usdc_spent"] = self.memory.state.get("usdc_spent", 0.0) + self.cost_optimizer.guess_cost_usdc
                        self.metrics.record_guess(is_correct=is_correct, cost=self.cost_optimizer.guess_cost_usdc)
                        
                        if is_correct:
                            logger.info(f"[bold green]>>> Checkpoint {current_point} SOLVED with desperation guess! <<<[/bold green]")
                            await self._wait_for_checkpoint_advance(current_point)
                        else:
                            self.candidate_manager.candidates[top_candidate] = 0.0
                            logger.warning(f"Desperation guess '{canonical_guess}' failed. Regrowing candidates...")
                            candidates = await self.kb.get_candidates(hint, history_list, force_refresh=True, bypass_offline=True)
                            if not candidates:
                                candidates = await self.kb.get_candidates(hint, history_list, force_refresh=True)
                            self.candidate_manager.set_candidates(candidates)
                        
                        self.memory.save()
                        await asyncio.sleep(1.0)
                        continue

                info_gain = score.get("info_gain", 0.0)

                # 7. Ask Oracle
                start_ask_time = time.time()
                answer = await self.oracle.ask(best_q)
                ask_latency = time.time() - start_ask_time
                
                # Handle UNKNOWN/MAYBE answers — skip this Q&A, don't record spend
                if answer == "UNKNOWN":
                    logger.warning(f"[orange3]Oracle returned UNKNOWN for '{best_q}'. Skipping — no spend recorded.[/orange3]")
                    # Still record in history to avoid re-asking the same useless question
                    history_list.append({"question": best_q, "answer": answer})
                    self.memory.state["history"] = history_list
                    self.memory.save()
                    await asyncio.sleep(0.1)
                    continue
                
                # Record in history & memory
                history_list.append({"question": best_q, "answer": answer})
                self.memory.state["history"] = history_list
                self.memory.state["question_count"] = self.memory.state.get("question_count", 0) + 1
                self.cost_optimizer.record_spend(self.cost_optimizer.ask_cost_usdc)
                self.memory.state["usdc_spent"] = self.memory.state.get("usdc_spent", 0.0) + self.cost_optimizer.ask_cost_usdc
                
                # Prune candidates based on Oracle response
                prev_candidate_count = len(active_candidates)
                await self.candidate_manager.update_probabilities(best_q, answer)
                post_candidate_count = len(self.candidate_manager.get_active_candidates())
                
                # Calculate reduction rate
                reduction_rate = (
                    (prev_candidate_count - post_candidate_count) / prev_candidate_count
                    if prev_candidate_count > 0 else 0.0
                )
                
                # Record metrics
                self.metrics.record_ask(ask_latency, self.cost_optimizer.ask_cost_usdc, info_gain, reduction_rate)
                
                # Record question effectiveness in learning database
                self.learning.record_question_effectiveness(hint, best_q, info_gain)
                
                # Save state
                self.memory.state["candidate_probabilities"] = self.candidate_manager.candidates.copy()
                self.memory.save()
                
                # Minimal delay to prevent server rate limiting
                await asyncio.sleep(0.1)
                
            except Exception as loop_err:
                err_str = str(loop_err)
                logger.error(f"[red]Error in race loop step: {err_str}[/red]")
                cached_race_state = None  # Force refresh on error
                if "sigil debit failed" in err_str.lower() or "insufficient" in err_str.lower() or "policy limit" in err_str.lower():
                    logger.warning("[bold red]💳 Sigil debit limit or spend cap reached. Syncing wallet status...[/bold red]")
                    try:
                        bal = await self.client.sigil_balance()
                        s_bal = bal.get("sigilBalance", {})
                        if s_bal.get("creditStatus") == "failed" or float(s_bal.get("balanceUsd", 0)) <= 0.001:
                            logger.error("[bold red]Wallet credit/balance exhausted. Standing by for race conclusion...[/bold red]")
                            await asyncio.sleep(15.0)
                            continue
                    except Exception:
                        pass
                await asyncio.sleep(3.0)

        # Stop race metrics and learning
        self.metrics.stop_race()
        summary = self.metrics.get_summary()
        self.learning.record_race_results(summary)
        
        logger.info(f"\n[bold green]=== RACE COMPLETED ===[/bold green]")
        logger.info(f"Duration: {summary['total_race_time_seconds']:.2f}s")
        logger.info(f"Paid Questions (Asks): {summary['total_asks']}")
        logger.info(f"Guesses: {summary['total_guesses']}")
        logger.info(f"USDC Spent: ${summary['total_usdc_spent']:.4f}")
        logger.info(f"USDC Saved (Est): ${summary['estimated_usdc_saved']:.4f}")
        
        # Reset memory for next race
        self.memory.reset()
        await self.client.shutdown()

    def _is_guess_correct(self, result: Any) -> bool:
        """Safely checks if a guess response is correct, handling case-insensitive dict keys like CORRECT and STATUS."""
        if isinstance(result, dict):
            res_lower = {str(k).lower(): v for k, v in result.items()}
            val = res_lower.get("correct")
            if val is True or (isinstance(val, str) and val.lower() == "true"):
                return True
            status_val = res_lower.get("status")
            if isinstance(status_val, str) and status_val.lower() in ("correct", "success"):
                return True
            verdict_val = res_lower.get("verdict")
            if isinstance(verdict_val, str) and verdict_val.lower() in ("correct", "true", "yes"):
                return True
            return False
        elif isinstance(result, str):
            res_lower = result.strip().lower()
            return res_lower in ("correct", "true", "success")
        return False

    async def _wait_for_checkpoint_advance(self, old_checkpoint: int, timeout_seconds: int = 15) -> None:
        """Blocks and polls the server state until the checkpoint increases, preventing double guesses."""
        logger.info(f"[cyan]Waiting for server to advance from checkpoint {old_checkpoint}...[/cyan]")
        start_time = asyncio.get_event_loop().time()
        consecutive_errors = 0
        while asyncio.get_event_loop().time() - start_time < timeout_seconds:
            try:
                state = await self.client.my_race()
                consecutive_errors = 0  # reset on success
                run_info = self._extract_run_info(state)
                current_point = self._extract_current_point(run_info) if run_info else None
                status = run_info.get("status", "").upper() if run_info else ""
                
                if current_point is not None and int(current_point) > int(old_checkpoint):
                    logger.info(f"[green]Server state advanced to checkpoint {current_point}.[/green]")
                    return
                if status in ("FINISHED", "COMPLETED", "WON", "OVER") or (run_info and (run_info.get("over") or run_info.get("isFinished") or run_info.get("finished"))) or state.get("finished"):
                    logger.info("[green]Server state marked as finished.[/green]")
                    return
            except Exception as e:
                consecutive_errors += 1
                logger.warning(f"Error checking checkpoint advance ({consecutive_errors}/3): {e}")
                if consecutive_errors >= 3:
                    logger.warning("[orange3]Too many consecutive errors checking checkpoint state. Breaking wait loop early.[/orange3]")
                    return
            await asyncio.sleep(0.2)
        logger.warning(f"[orange3]Timed out waiting for checkpoint to advance. Proceeding anyway.[/orange3]")

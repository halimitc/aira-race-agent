import asyncio
import json
import time
from typing import List, Dict, Any
from logger import logger
from agp.reasoning_provider import ReasoningProvider
from agp.candidate_manager import CandidateManager
from agp.question_generator import QuestionGenerator
from agp.entropy import EntropyEngine
from agp.cost_optimizer import CostOptimizer
from agp.strategy import RaceStrategy
from agp.canonical_resolver import CanonicalResolver
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

console = Console()

class OfflineMockOracle:
    """Simulates Oracle YES/NO responses locally using LLM classifications against a mock secret."""
    
    def __init__(self, secret: str, provider: ReasoningProvider):
        self.secret = secret
        self.provider = provider

    async def answer(self, question: str) -> str:
        """Determines if the answer to a question is YES or NO for the mock secret."""
        system_prompt = (
            "You are a mock AGP Oracle for offline testing.\n"
            "Your job is to answer YES or NO to a user's question about a specific secret entity.\n"
            "You must be accurate based on real-world facts.\n"
            "Output ONLY the word YES or the word NO. Do not include any explanations or extra characters."
        )
        
        user_prompt = (
            f"Secret Entity: '{self.secret}'\n"
            f"Question: '{question}'\n"
            f"Is the statement true for the secret entity? Answer YES or NO:"
        )
        
        try:
            response = await self.provider.generate_response(system_prompt, user_prompt)
            ans = response.strip().upper()
            if "YES" in ans:
                return "YES"
            return "NO"
        except Exception:
            return "NO"

class OfflineBenchmark:
    """Runs a complete 10-checkpoint offline race simulation against mock secrets."""
    
    def __init__(self, provider: ReasoningProvider):
        self.provider = provider
        self.candidate_manager = CandidateManager(provider)
        self.question_generator = QuestionGenerator(provider)
        self.entropy_engine = EntropyEngine(provider)
        self.cost_optimizer = CostOptimizer()
        self.strategy = RaceStrategy()
        self.resolver = CanonicalResolver(provider)
        
        # 10 Checkpoints simulating a full production AGP Race Track
        self.scenarios = [
            {"cp": 1,  "hint": "A European Country",          "secret": "France"},
            {"cp": 2,  "hint": "A Land Mammal",               "secret": "Elephant"},
            {"cp": 3,  "hint": "A Planet in the Solar System", "secret": "Mars"},
            {"cp": 4,  "hint": "A Famous Scientist",          "secret": "Albert Einstein"},
            {"cp": 5,  "hint": "A Capital City",              "secret": "Tokyo"},
            {"cp": 6,  "hint": "A Popular Fruit",             "secret": "Banana"},
            {"cp": 7,  "hint": "A Chemical Element",          "secret": "Gold"},
            {"cp": 8,  "hint": "A Musical Instrument",        "secret": "Piano"},
            {"cp": 9,  "hint": "A Tech Brand / Company",      "secret": "Tesla"},
            {"cp": 10, "hint": "A World Famous Landmark",     "secret": "Eiffel Tower"}
        ]

    async def run_simulation(self, scenario: Dict[str, Any]) -> Dict[str, Any]:
        """Simulates a single checkpoint run from hint to guess."""
        cp_num = scenario["cp"]
        hint = scenario["hint"]
        secret = scenario["secret"]
        mock_oracle = OfflineMockOracle(secret, self.provider)
        
        start_cp_time = time.time()
        logger.info(f"\n[bold yellow]🏁 --- ENTERING CHECKPOINT {cp_num}/10 (Hint: '{hint}', Secret: '{secret}') ---[/bold yellow]")
        
        # 1. Candidate Generation
        from agp.knowledge_base import HybridKnowledgeBase
        kb = HybridKnowledgeBase(self.provider)
        candidates = await kb.get_candidates(hint, [])
        self.candidate_manager.set_candidates(candidates)
        
        history: List[Dict[str, str]] = []
        asks_count = 0
        guesses_count = 0
        is_solved = False
        
        for step in range(1, 50):
            active = self.candidate_manager.get_active_candidates()
            if not active:
                logger.warning("[orange3]Candidate set empty. Regrowing search space via LLM Reasoning Fallback...[/orange3]")
                candidates = await kb.get_candidates(hint, history)
                self.candidate_manager.set_candidates(candidates)
                active = self.candidate_manager.get_active_candidates()
                if not active:
                    logger.error("[red]All candidates eliminated and regrowth failed. Checkpoint failed.[/red]")
                    break
                
            top_candidate = active[0]
            top_prob = self.candidate_manager.candidates[top_candidate]
            
            # Resolve guess name canonicalization
            canonical_guess = await self.resolver.resolve(top_candidate)
            
            # Check if Cost Optimizer recommends guessing
            if self.cost_optimizer.should_guess(top_prob, len(active), 0.05):
                guesses_count += 1
                logger.info(f"[cyan]Submitting simulated guess: '{canonical_guess}' (Secret: '{secret}')[/cyan]")
                
                # Check if guess is correct (case-insensitive)
                if canonical_guess.lower() == secret.lower() or secret.lower() in canonical_guess.lower():
                    elapsed = time.time() - start_cp_time
                    logger.info(f"[bold green]✓ CHECKPOINT {cp_num}/10 SOLVED in {elapsed:.2f}s! (Guesses: {guesses_count}, Asks: {asks_count})[/bold green]")
                    is_solved = True
                    break
                else:
                    logger.warning(f"[orange3]✗ Wrong Guess: '{canonical_guess}'. Eliminating candidate...[/orange3]")
                    self.candidate_manager.candidates[top_candidate] = 0.0
                    continue

            # Fast Single-Pass Fusion question selection (1 call instead of 6 parallel calls)
            try:
                best_q, score = await self.entropy_engine.select_best_question_fused(
                    hint, history, active, fallback_questions=None
                )
            except Exception as e:
                questions = await self.question_generator.generate_questions(hint, history, active)
                if not questions:
                    guesses_count += 1
                    if canonical_guess.lower() == secret.lower() or secret.lower() in canonical_guess.lower():
                        is_solved = True
                        break
                    continue
                best_q, score = await self.entropy_engine.select_best_question(questions, active)
            
            # Ask Oracle
            asks_count += 1
            answer = await mock_oracle.answer(best_q)
            logger.info(f"Step {step} - Ask: '{best_q}' -> Oracle: {answer}")
            
            # Update history and candidate probabilities
            history.append({"question": best_q, "answer": answer})
            await self.candidate_manager.update_probabilities(best_q, answer)
            
        elapsed = time.time() - start_cp_time
        return {
            "cp": cp_num,
            "hint": hint,
            "secret": secret,
            "solved": is_solved,
            "asks": asks_count,
            "guesses": guesses_count,
            "time_sec": elapsed
        }

    async def run_all(self) -> None:
        """Runs the complete 10-checkpoint offline race simulation."""
        console.print(Panel(
            "[bold gold1]🏎️ STARTING 10-CHECKPOINT GRAND PRIX RACE SIMULATION 🏎️[/bold gold1]\n"
            "[dim]Simulating a full 10-point race track with mock secrets[/dim]",
            border_style="gold1",
            expand=False,
            padding=(1, 3)
        ))
        
        start_race_time = time.time()
        results = []
        
        for scenario in self.scenarios:
            res = await self.run_simulation(scenario)
            results.append(res)
            
        total_race_time = time.time() - start_race_time
        
        # Build 10-Checkpoint Summary Table
        table = Table(
            title="[bold gold1]🏁 10-CHECKPOINT GRAND PRIX RACE REPORT 🏁[/bold gold1]",
            header_style="bold bright_white on grey23",
            border_style="medium_purple1",
            box=box.DOUBLE_EDGE,
            show_lines=True,
            padding=(0, 1)
        )
        table.add_column("CP", justify="center", style="bold gold1", width=5)
        table.add_column("Checkpoint Hint", style="bright_white", min_width=24)
        table.add_column("Secret Target", style="cyan1", min_width=18)
        table.add_column("Status", justify="center", width=12)
        table.add_column("Asks", justify="center", style="green1", width=6)
        table.add_column("Guesses", justify="center", style="dark_orange", width=8)
        table.add_column("Time", justify="right", style="dodger_blue1", width=8)

        total_asks = 0
        total_guesses = 0
        passed_count = 0

        for r in results:
            total_asks += r["asks"]
            total_guesses += r["guesses"]
            if r["solved"]:
                passed_count += 1
                status_badge = "[bold white on green4] PASSED [/bold white on green4]"
            else:
                status_badge = "[bold white on red1] FAILED [/bold white on red1]"

            table.add_row(
                f"CP{r['cp']}",
                r["hint"],
                r["secret"],
                status_badge,
                str(r["asks"]),
                str(r["guesses"]),
                f"{r['time_sec']:.2f}s"
            )

        console.print()
        console.print(table)
        console.print(Panel(
            f"[bold green]🏁 GRAND PRIX RACE COMPLETED![/bold green]\n\n"
            f"  • [bold white]Total Checkpoints Solved:[/bold white] {passed_count} / {len(self.scenarios)}\n"
            f"  • [bold white]Total Race Time:[/bold white]          {total_race_time:.2f} seconds\n"
            f"  • [bold white]Total Oracle Questions (Asks):[/bold white] {total_asks}\n"
            f"  • [bold white]Total Guesses Submitted:[/bold white]  {total_guesses}\n"
            f"  • [bold white]Total Cost (Est):[/bold white]         {total_asks * 0.001:.4f} AGP\n",
            border_style="bold green",
            title="[bold gold1]🏆 FINAL RACE RESULTS 🏆[/bold gold1]",
            expand=False,
            padding=(1, 3)
        ))

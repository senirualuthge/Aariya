"""
Rich CLI Display System for AI Girl Brain Server.
Provides structured, visualized console output using the Rich library.
"""

from datetime import datetime
from typing import Dict, Any, Optional, List
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.progress_bar import ProgressBar
from rich.text import Text
from rich.align import Align
from rich import box

class RichDisplay:
    """Rich CLI display for server monitoring."""
    
    def __init__(self):
        self.console = Console()
        self.session_count = 0
        self.total_turns = 0
        self.start_time = datetime.now()
    
    def _timestamp(self) -> str:
        """Get formatted timestamp."""
        return datetime.now().strftime("%H:%M:%S")

    def print_banner(self):
        """Print startup banner."""
        title = Text("AI GIRL BRAIN - FIXV2 ENHANCED", style="bold white on blue", justify="center")
        subtitle = Text("Production-Grade AI Runtime with Trust & Safety", style="yellow", justify="center")
        
        panel = Panel(
            Align.center(Text.assemble(title, "\n", subtitle)),
            box=box.DOUBLE,
            style="cyan",
            padding=(1, 2)
        )
        self.console.print(panel)

    def print_system_info(self, redis_available: bool, postgres_available: bool, neural_available: bool):
        """Print system configuration."""
        table = Table(title="System Configuration", box=box.ROUNDED, show_header=False)
        table.add_column("Component", style="cyan")
        table.add_column("Status")

        table.add_row(
            "Database", 
            "[green]PostgreSQL[/green]" if postgres_available else "[yellow]SQLite (Fallback)[/yellow]"
        )
        table.add_row(
            "Cache", 
            "[green]Redis[/green]" if redis_available else "[yellow]In-Memory (Fallback)[/yellow]"
        )
        table.add_row(
            "Neural Policy", 
            "[green]TensorFlow Active[/green]" if neural_available else "[yellow]Heuristic Fallback[/yellow]"
        )
        table.add_row("Version", "2.0.0-fixv2")
        
        self.console.print(table)

    def print_startup_complete(self, host: str, port: int):
        """Print server ready message."""
        self.console.print(f"[bold green]✓ Server Ready[/bold green]")
        self.console.print(f"  Listening on: [bold white]ws://{host}:{port}/ws/brain[/bold white]")
        self.console.print(f"  Health Check: [bold white]http://{host}:{port}/health[/bold white]")
        self.console.print(f"\n[dim]Waiting for connections...[/dim]\n")

    def print_session_start(self, session_id: str, user_id: str, initial_trust: float):
        """Print session start information."""
        self.session_count += 1
        self.console.print(f"\n[bold cyan]╔═══ NEW SESSION ═══════════════════════════════════════════╗[/bold cyan]")
        self.console.print(f"[bold cyan]║[/bold cyan] Session ID:    {session_id[:8]}...")
        self.console.print(f"[bold cyan]║[/bold cyan] User ID:       {user_id}")
        self.console.print(f"[bold cyan]║[/bold cyan] Initial Trust: {initial_trust:.2f}")
        self.console.print(f"[bold cyan]╚═══════════════════════════════════════════════════════════╝[/bold cyan]\n")

    def print_turn_info(
        self,
        turn_number: int,
        inputs: Dict[str, Any],
        brain_state: Dict[str, Any],
        decision_trace: Dict[str, Any],
        latency_ms: float
    ):
        """
        Print detailed turn information using a grid layout.
        
        Args:
            turn_number: The curent turn number
            inputs: Dict with 'text', 'voice', 'vision' keys
            brain_state: Dict with 'trust', 'contradiction', 'emotion', 'state'
            decision_trace: Dict with 'proposed_action', 'safe_action', 'safety_violations'
            latency_ms: Total turn latency
        """
        self.total_turns += 1
        
        # 1. Input Panel
        input_table = Table(box=box.SIMPLE, show_header=False, padding=(0,1))
        input_table.add_column("Type", style="cyan")
        input_table.add_column("Content")
        
        if inputs.get("text"):
            input_table.add_row("Text", f"'{inputs['text']}'")
        
        vision = inputs.get("vision", {})
        if vision:
            face = f"Val:{vision.get('face_valence',0):.2f} Aro:{vision.get('face_arousal',0):.2f}"
            voice = f"Val:{vision.get('voice_valence',0):.2f} Aro:{vision.get('voice_arousal',0):.2f}"
            input_table.add_row("Vision", face)
            input_table.add_row("Voice", voice)

        # 2. State Panel
        state_table = Table(box=box.SIMPLE, show_header=False, padding=(0,1))
        state_table.add_column("Metric", style="yellow")
        state_table.add_column("Value")
        
        # Trust Bar
        trust_val = brain_state.get('trust', 0.5)
        trust_color = "green" if trust_val > 0.7 else "yellow" if trust_val > 0.4 else "red"
        state_table.add_row("Trust", f"[{trust_color}]{trust_val:.2f}[/{trust_color}] ({brain_state.get('state', 'UNKNOWN')})")
        
        # Contradiction Bar
        contra_val = brain_state.get('contradiction', 0.0)
        contra_color = "red" if contra_val > 0.5 else "green"
        state_table.add_row("Contradiction", f"[{contra_color}]{contra_val:.2f}[/{contra_color}]")
        
        # 3. Decision Logic Table
        logic_table = Table(title="Decision Logic", box=box.ROUNDED, show_header=True)
        logic_table.add_column("Step", style="dim")
        logic_table.add_column("Action / Output")
        
        # Neural Proposal
        proposed = decision_trace.get('proposed_action', {})
        logic_table.add_row("Neural Net", str(proposed))
        
        # Safety Violations
        violations = decision_trace.get('safety_violations', [])
        if violations:
            for v in violations:
                logic_table.add_row("[red]Safety Violation[/red]", f"[red]{v}[/red]")
        
        # Final Action
        final = decision_trace.get('safe_action', {})
        logic_table.add_row("[bold green]Final Action[/bold green]", str(final))

        # 4. Latency Footer
        latency_color = "green" if latency_ms < 500 else "yellow" if latency_ms < 1500 else "red"
        footer = f"Latency: [{latency_color}]{latency_ms:.0f}ms[/{latency_color}] | Turn: {turn_number}"

        # Combine into Main Layout
        main_grid = Table.grid(expand=True)
        main_grid.add_row(Panel(input_table, title="[bold]Inputs[/bold]", border_style="blue"))
        main_grid.add_row(Panel(state_table, title="[bold]Brain State[/bold]", border_style="yellow"))
        main_grid.add_row(Panel(logic_table, title="[bold]Processing[/bold]", border_style="magenta"))
        
        self.console.print(Panel(main_grid, title=f"Turn {turn_number}", subtitle=footer, border_style="white"))

    def print_session_end(self, session_id: str, duration: int, turns: int, trust: float):
        """Print session end summary."""
        self.console.print(f"\n[bold cyan]╔═══ SESSION END ═══════════════════════════════════════════╗[/bold cyan]")
        self.console.print(f"[bold cyan]║[/bold cyan] Duration:    {duration}s ({turns} turns)")
        self.console.print(f"[bold cyan]║[/bold cyan] Final Trust: {trust:.2f}")
        self.console.print(f"[bold cyan]╚═══════════════════════════════════════════════════════════╝[/bold cyan]\n")

    def print_error(self, error_type: str, message: str):
        self.console.print(f"[bold red]✗ ERROR [{error_type}]:[/bold red] {message}")

# Global instance
_rich_display: Optional[RichDisplay] = None

def get_rich_display() -> RichDisplay:
    """Get or create global Rich CLI display instance."""
    global _rich_display
    if _rich_display is None:
        _rich_display = RichDisplay()
    return _rich_display

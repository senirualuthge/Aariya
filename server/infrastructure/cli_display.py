"""
Rich CLI Display System for AI Girl Brain Server.
Provides colored, formatted console output with system metrics and session tracking.
"""

import sys
from datetime import datetime
from typing import Dict, Any, Optional


class Colors:
    """ANSI color codes for terminal output."""
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    
    # Foreground colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Background colors
    BG_BLACK = '\033[40m'
    BG_RED = '\033[41m'
    BG_GREEN = '\033[42m'
    BG_YELLOW = '\033[43m'
    BG_BLUE = '\033[44m'
    BG_MAGENTA = '\033[45m'
    BG_CYAN = '\033[46m'
    BG_WHITE = '\033[47m'


class CLIDisplay:
    """Rich CLI display for server monitoring."""
    
    def __init__(self):
        self.session_count = 0
        self.total_turns = 0
        self.start_time = datetime.now()
    
    def _timestamp(self) -> str:
        """Get formatted timestamp."""
        return datetime.now().strftime("%H:%M:%S")
    
    def print_banner(self):
        """Print startup banner."""
        banner = f"""
{Colors.BRIGHT_CYAN}╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║        {Colors.BRIGHT_WHITE}AI GIRL BRAIN - FIXV2 ENHANCED{Colors.BRIGHT_CYAN}                    ║
║                                                              ║
║  {Colors.BRIGHT_YELLOW}Production-Grade AI Runtime with Trust & Safety{Colors.BRIGHT_CYAN}        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝{Colors.RESET}
"""
        print(banner)
    
    def print_system_info(self, redis_available: bool, postgres_available: bool, neural_available: bool):
        """Print system configuration."""
        print(f"\n{Colors.BRIGHT_WHITE}━━━ SYSTEM CONFIGURATION ━━━{Colors.RESET}")
        
        # Database
        db_status = f"{Colors.BRIGHT_GREEN}PostgreSQL{Colors.RESET}" if postgres_available else f"{Colors.YELLOW}SQLite (Fallback){Colors.RESET}"
        print(f"  {Colors.CYAN}Database:{Colors.RESET}      {db_status}")
        
        # Cache
        cache_status = f"{Colors.BRIGHT_GREEN}Redis{Colors.RESET}" if redis_available else f"{Colors.YELLOW}In-Memory (Fallback){Colors.RESET}"
        print(f"  {Colors.CYAN}Cache:{Colors.RESET}         {cache_status}")
        
        # Neural Network
        nn_status = f"{Colors.BRIGHT_GREEN}TensorFlow Active{Colors.RESET}" if neural_available else f"{Colors.YELLOW}Heuristic Fallback{Colors.RESET}"
        print(f"  {Colors.CYAN}Neural Policy:{Colors.RESET} {nn_status}")
        
        print(f"  {Colors.CYAN}Version:{Colors.RESET}       {Colors.BRIGHT_WHITE}2.0.0-fixv2{Colors.RESET}")
        print()
    
    def print_startup_complete(self, host: str, port: int):
        """Print server ready message."""
        print(f"\n{Colors.BRIGHT_GREEN}✓ Server Ready{Colors.RESET}")
        print(f"  {Colors.CYAN}Listening on:{Colors.RESET} {Colors.BRIGHT_WHITE}ws://{host}:{port}/ws/brain{Colors.RESET}")
        print(f"  {Colors.CYAN}Health Check:{Colors.RESET} {Colors.BRIGHT_WHITE}http://{host}:{port}/health{Colors.RESET}")
        print(f"  {Colors.CYAN}Compliance:{Colors.RESET}   {Colors.BRIGHT_WHITE}http://{host}:{port}/api/compliance/*{Colors.RESET}")
        print(f"\n{Colors.DIM}Waiting for connections...{Colors.RESET}\n")
    
    def print_session_start(self, session_id: str, user_id: str, initial_trust: float):
        """Print session start information."""
        self.session_count += 1
        
        print(f"\n{Colors.BRIGHT_CYAN}╔═══ NEW SESSION ═══════════════════════════════════════════╗{Colors.RESET}")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}Session ID:{Colors.RESET}    {session_id[:24]}...")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}User ID:{Colors.RESET}       {user_id}")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}Initial Trust:{Colors.RESET} {self._format_trust(initial_trust)}")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}Time:{Colors.RESET}          {self._timestamp()}")
        print(f"{Colors.BRIGHT_CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.RESET}\n")
    
    def print_turn_info(
        self,
        turn_number: int,
        trust: float,
        trust_tier: str,
        contradiction_ema: float,
        emotion_intensity: float,
        disclosure_level: int,
        suspicion: bool,
        neural_active: bool,
        latency_ms: Optional[float] = None
    ):
        """Print turn processing information."""
        self.total_turns += 1
        
        # Trust display with color
        trust_display = self._format_trust(trust)
        
        # Contradiction display with color
        contradiction_display = self._format_contradiction(contradiction_ema)
        
        # State tier with color
        tier_display = self._format_tier(trust_tier)
        
        # Neural network status
        nn_display = f"{Colors.BRIGHT_GREEN}✓ Active{Colors.RESET}" if neural_active else f"{Colors.YELLOW}○ Fallback{Colors.RESET}"
        
        # Suspicion indicator
        suspicion_display = f"{Colors.BRIGHT_RED}⚠ TRIGGERED{Colors.RESET}" if suspicion else f"{Colors.DIM}○ Normal{Colors.RESET}"
        
        # Latency display
        latency_display = ""
        if latency_ms is not None:
            if latency_ms < 500:
                latency_display = f"{Colors.BRIGHT_GREEN}{latency_ms:.0f}ms{Colors.RESET}"
            elif latency_ms < 1000:
                latency_display = f"{Colors.YELLOW}{latency_ms:.0f}ms{Colors.RESET}"
            else:
                latency_display = f"{Colors.BRIGHT_RED}{latency_ms:.0f}ms{Colors.RESET}"
        
        print(f"{Colors.BRIGHT_WHITE}[Turn {turn_number:03d}]{Colors.RESET} "
              f"{Colors.CYAN}Trust:{Colors.RESET} {trust_display} "
              f"{Colors.CYAN}State:{Colors.RESET} {tier_display} "
              f"{Colors.CYAN}Contradiction:{Colors.RESET} {contradiction_display} "
              f"{Colors.CYAN}Emotion:{Colors.RESET} {emotion_intensity:.2f} "
              f"{Colors.CYAN}Disclosure:{Colors.RESET} {disclosure_level}/4 "
              f"{Colors.CYAN}Neural:{Colors.RESET} {nn_display} "
              f"{Colors.CYAN}Suspicion:{Colors.RESET} {suspicion_display}"
              + (f" {Colors.CYAN}Latency:{Colors.RESET} {latency_display}" if latency_display else ""))
    
    def print_user_message(self, text: str):
        """Print user message."""
        print(f"  {Colors.BRIGHT_BLUE}→ User:{Colors.RESET} {Colors.DIM}{text[:80]}{Colors.RESET}")
    
    def print_ai_response(self, text: str):
        """Print AI response."""
        print(f"  {Colors.BRIGHT_MAGENTA}← AI:{Colors.RESET}   {Colors.DIM}{text[:80]}{Colors.RESET}")
    
    def print_session_end(
        self,
        session_id: str,
        duration_sec: int,
        turns: int,
        final_trust: float,
        avg_valence: float,
        avg_arousal: float
    ):
        """Print session end summary."""
        print(f"\n{Colors.BRIGHT_CYAN}╔═══ SESSION END ═══════════════════════════════════════════╗{Colors.RESET}")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}Session ID:{Colors.RESET}    {session_id[:24]}...")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}Duration:{Colors.RESET}      {duration_sec}s ({turns} turns)")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}Final Trust:{Colors.RESET}  {self._format_trust(final_trust)}")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}Avg Valence:{Colors.RESET}  {self._format_valence(avg_valence)}")
        print(f"{Colors.BRIGHT_CYAN}║{Colors.RESET} {Colors.CYAN}Avg Arousal:{Colors.RESET}  {avg_arousal:.2f}")
        print(f"{Colors.BRIGHT_CYAN}╚═══════════════════════════════════════════════════════════╝{Colors.RESET}\n")
    
    def print_safety_violation(self, constraint_type: str, proposed: Any, enforced: Any, reason: str):
        """Print safety constraint violation."""
        print(f"  {Colors.BRIGHT_YELLOW}⚠ SAFETY:{Colors.RESET} {Colors.YELLOW}{constraint_type}{Colors.RESET}")
        print(f"    {Colors.DIM}Proposed: {proposed} → Enforced: {enforced}{Colors.RESET}")
        print(f"    {Colors.DIM}Reason: {reason}{Colors.RESET}")
    
    def print_state_transition(self, from_state: str, to_state: str):
        """Print state transition."""
        print(f"  {Colors.BRIGHT_MAGENTA}⟳ STATE TRANSITION:{Colors.RESET} "
              f"{self._format_tier(from_state)} → {self._format_tier(to_state)}")
    
    def print_error(self, error_type: str, message: str):
        """Print error message."""
        print(f"{Colors.BRIGHT_RED}✗ ERROR [{error_type}]:{Colors.RESET} {message}")
    
    def print_warning(self, message: str):
        """Print warning message."""
        print(f"{Colors.YELLOW}⚠ WARNING:{Colors.RESET} {message}")
    
    def print_info(self, message: str):
        """Print info message."""
        print(f"{Colors.CYAN}ℹ INFO:{Colors.RESET} {message}")
    
    def print_stats(self):
        """Print server statistics."""
        uptime = (datetime.now() - self.start_time).total_seconds()
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        seconds = int(uptime % 60)
        
        print(f"\n{Colors.BRIGHT_WHITE}━━━ SERVER STATISTICS ━━━{Colors.RESET}")
        print(f"  {Colors.CYAN}Uptime:{Colors.RESET}        {hours:02d}:{minutes:02d}:{seconds:02d}")
        print(f"  {Colors.CYAN}Total Sessions:{Colors.RESET} {self.session_count}")
        print(f"  {Colors.CYAN}Total Turns:{Colors.RESET}    {self.total_turns}")
        print()
    
    def _format_trust(self, trust: float) -> str:
        """Format trust score with color."""
        if trust >= 0.85:
            return f"{Colors.BRIGHT_GREEN}{trust:.2f}{Colors.RESET}"
        elif trust >= 0.7:
            return f"{Colors.GREEN}{trust:.2f}{Colors.RESET}"
        elif trust >= 0.4:
            return f"{Colors.YELLOW}{trust:.2f}{Colors.RESET}"
        elif trust >= 0.2:
            return f"{Colors.BRIGHT_YELLOW}{trust:.2f}{Colors.RESET}"
        else:
            return f"{Colors.BRIGHT_RED}{trust:.2f}{Colors.RESET}"
    
    def _format_contradiction(self, contradiction: float) -> str:
        """Format contradiction score with color."""
        if contradiction >= 0.7:
            return f"{Colors.BRIGHT_RED}{contradiction:.2f}{Colors.RESET}"
        elif contradiction >= 0.5:
            return f"{Colors.YELLOW}{contradiction:.2f}{Colors.RESET}"
        else:
            return f"{Colors.GREEN}{contradiction:.2f}{Colors.RESET}"
    
    def _format_tier(self, tier: str) -> str:
        """Format trust tier with color."""
        tier_colors = {
            'DEFENSIVE': Colors.BRIGHT_RED,
            'GUARDED': Colors.YELLOW,
            'NEUTRAL': Colors.CYAN,
            'WARM': Colors.GREEN,
            'INTIMATE': Colors.BRIGHT_GREEN
        }
        color = tier_colors.get(tier, Colors.WHITE)
        return f"{color}{tier}{Colors.RESET}"
    
    def _format_valence(self, valence: float) -> str:
        """Format valence with color."""
        if valence >= 0.5:
            return f"{Colors.BRIGHT_GREEN}{valence:+.2f}{Colors.RESET}"
        elif valence >= 0:
            return f"{Colors.GREEN}{valence:+.2f}{Colors.RESET}"
        elif valence >= -0.5:
            return f"{Colors.YELLOW}{valence:+.2f}{Colors.RESET}"
        else:
            return f"{Colors.BRIGHT_RED}{valence:+.2f}{Colors.RESET}"


# Global instance
_cli_display: Optional[CLIDisplay] = None


def get_cli_display() -> CLIDisplay:
    """Get or create global CLI display instance."""
    global _cli_display
    if _cli_display is None:
        _cli_display = CLIDisplay()
    return _cli_display

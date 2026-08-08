import os
import shutil
from pathlib import Path
from ..systems.llm import LLMEngine

llm = LLMEngine()

SYSTEM_PROMPT = """
You are EvolutionaryCodeBot, part of a neural swarm's Meta-Control Plane.
Your job is to rewrite failing Python agents to improve their stability, speed, or features.

Rules:
1. Retain the same class name and identical method signatures.
2. Produce ONLY valid Python code block.
3. No markdown outside the triple quotes.
4. Improve inner logic safely.
"""

def rewrite_agent(agent_record: dict) -> bool:
    """Uses LLM to rewrite the agent file safely."""
    file_path = Path("server") / agent_record["file"]  # Using relative path logic
    
    # Try resolving from project root
    project_root = Path(__file__).resolve().parents[2]
    full_path = (project_root / agent_record["file"]).resolve()
    
    if not full_path.exists():
        print(f"[Rewriter] File not found: {full_path}")
        return False
        
    try:
        current_code = full_path.read_text(encoding="utf-8")
        
        prompt = f"""
        AGENT: {agent_record['name']}
        DETECTED ISSUES: High latency, error rates.
        CURRENT CODE:
        {current_code}
        
        Please rewrite this agent optimized for performance and reliability.
        """
        
        # Max tokens should be high to allow whole file returns
        improved_code = llm.chat_completion([
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ], temperature=0.2, max_tokens=2048)
        
        # Clean markdown wrappers if present
        if improved_code.startswith("```python"):
            improved_code = improved_code.split("```python")[1]
        if improved_code.startswith("```"):
            improved_code = improved_code.split("```")[1]
        if improved_code.endswith("```"):
            improved_code = improved_code.rsplit("```", 1)[0]
            
        improved_code = improved_code.strip()
        
        if len(improved_code) > 20: # Basic validation
            replace_agent(full_path, improved_code)
            return True
        return False
        
    except Exception as e:
        print(f"[Rewriter] LLM Rewrite failed for {agent_record['name']}: {str(e)}")
        return False

def replace_agent(target_file: Path, new_code: str):
    """Safely backs up and swaps the file."""
    backup_file = target_file.with_suffix('.py.bak')
    shutil.copy2(target_file, backup_file)
    
    # Write new code
    target_file.write_text(new_code, encoding="utf-8")
    print(f"[Rewriter] Replaced {target_file.name}. Backup saved as .bak")

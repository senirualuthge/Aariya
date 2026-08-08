from typing import List, Dict, Any

class RiskEngine:
    def calculate(self, issues: List[Dict[str, Any]]) -> Dict[str, Any]:
        score = 0
        
        for issue in issues:
            severity = issue.get("severity", "LOW")
            if severity == "HIGH":
                score += 3
            elif severity == "MEDIUM":
                score += 2
            else:
                score += 1
                
        return {
            "risk_score": score,
            "risk_level": (
                "HIGH" if score >= 5 else
                "MEDIUM" if score >= 2 else
                "LOW" if score > 0 else
                "SAFE"
            )
        }

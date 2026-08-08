from server.systems.llm import LLMEngine
import json

class SocialIntentSystem:
    def __init__(self, llm_engine: LLMEngine):
        self.llm = llm_engine
        self.current_intent = "LISTENING"

    def determine_intent(self, user_text, recent_history, current_emotion):
        """
        Uses LLM to determine the AI's social intent based on context.
        """
        system_prompt = f"""
        You are the 'Social Intent' module for an AI Girl. 
        Your goal is to determine the best social intent (stance) for the next response.
        
        Current AI Emotion: {json.dumps(current_emotion)}
        
        Available Intents:
        - LISTENING: Passive, attentive.
        - COMFORTING: User is sad/distressed.
        - FLIRTING: Playful, romantic context.
        - TEASING: Lighthearted banter.
        - INFORMING: Providing facts/answers.
        - DEFLECTING: User is being rude/inappropriate.
        
        Return ONLY a JSON object with keys:
        - 'intent': (one of the above)
        - 'reasoning': (short explanation)
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            *recent_history[-3:], # Last 3 messages for context
            {"role": "user", "content": f"User said: {user_text}"}
        ]
        
        try:
            response = self.llm.chat_completion(messages, temperature=0.5)
            # Clean possible markdown
            json_str = response.replace("```json", "").replace("```", "").strip()
            data = json.loads(json_str)
            self.current_intent = data.get("intent", "LISTENING")
            return self.current_intent, data.get("reasoning", "")
        except Exception as e:
            print(f"[SocialIntent] Error: {e}")
            return "LISTENING", "Fallback due to error"

"""
Phase 4: Reinforcement Learning Policy (PPO)
Wraps the PPOModel and implements a minimal Proximal Policy Optimization loop
that continuously fine-tunes the AI's conversational style based on user signals.

Action Space (5 styles that map to prompting modifiers):
    0 → supportive    – warm, validating, empathetic
    1 → playful       – light, teasing, energetic
    2 → assertive     – confident, direct, goal-oriented
    3 → reflective    – thoughtful, introspective, slow
    4 → neutral       – balanced, default fallback

State vector (5 dims):
    valence, arousal, trust, contradiction, history_len (normalized)
"""

import os
import torch
import torch.nn.functional as F
from typing import Dict

from .model import PPOModel, encode_state, select_action
from .reward import compute_reward

# ── Action space ───────────────────────────────────────────────────────────────
ACTION_STYLE_MAP = {
    0: "supportive",
    1: "playful",
    2: "assertive",
    3: "reflective",
    4: "neutral",
}

MODEL_PATH = os.path.join(os.path.dirname(__file__), "ppo_checkpoint.pt")

# ── Hyperparameters ────────────────────────────────────────────────────────────
GAMMA       = 0.99   # Discount factor
CLIP_RATIO  = 0.2    # PPO clip threshold
LR          = 3e-4
TRAIN_EVERY = 16     # Update model every N turns


class RolloutBuffer:
    """Stores experiences for one PPO update cycle."""
    def __init__(self):
        self.states:      list[torch.Tensor] = []
        self.actions:     list[int]          = []
        self.log_probs:   list[float]        = []
        self.rewards:     list[float]        = []
        self.values:      list[float]        = []

    def push(self, state, action, log_prob, reward, value):
        self.states.append(state)
        self.actions.append(action)
        self.log_probs.append(log_prob)
        self.rewards.append(reward)
        self.values.append(value)

    def compute_returns(self):
        """Compute discounted returns for the collected rollout."""
        G, returns = 0.0, []
        for r in reversed(self.rewards):
            G = r + GAMMA * G
            returns.insert(0, G)
        return torch.tensor(returns, dtype=torch.float32)

    def clear(self):
        self.__init__()

    def __len__(self):
        return len(self.states)


class PPOPolicy:
    """
    Full PPO training loop wired into the AI Girl conversation system.
    Call `select_style(context)` each turn to get a behavior modifier.
    Call `observe_outcome(prev_ctx, curr_ctx)` at turn end to store reward.
    Call `maybe_update()` periodically to run the PPO update step.
    """

    def __init__(self):
        self.model     = PPOModel(state_dim=5, num_actions=5)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=LR)
        self.buffer    = RolloutBuffer()
        self._last_action:   int   = 4  # start neutral
        self._last_log_prob: float = 0.0
        self._last_value:    float = 0.0
        self._last_state:    torch.Tensor | None = None
        self._turn_count:    int   = 0

        self._load_if_exists()

    # ── Public API ─────────────────────────────────────────────────────────────

    def select_style(self, context: Dict) -> str:
        """
        Given the current conversation context, return a style string
        that the system prompt modifier should apply this turn.

        Returns one of: supportive | playful | assertive | reflective | neutral
        """
        state_tensor      = encode_state(context)
        action, lp, value = select_action(self.model, state_tensor)

        self._last_action   = action
        self._last_log_prob = lp
        self._last_value    = value
        self._last_state    = state_tensor

        return ACTION_STYLE_MAP[action]

    def observe_outcome(self, prev_context: Dict, curr_context: Dict) -> float:
        """
        Record the result of the last turn. 
        Should be called AFTER the user has responded.
        
        Returns the computed reward scalar.
        """
        if self._last_state is None:
            return 0.0

        reward = compute_reward(prev_context, curr_context)

        self.buffer.push(
            state    = self._last_state,
            action   = self._last_action,
            log_prob = self._last_log_prob,
            reward   = reward,
            value    = self._last_value,
        )
        self._turn_count += 1
        return reward

    def maybe_update(self) -> bool:
        """
        Run a PPO gradient update if enough experience has accumulated.
        Returns True if an update was performed.
        """
        if len(self.buffer) < TRAIN_EVERY:
            return False

        self._ppo_update()
        self.buffer.clear()
        self._save()
        return True

    def get_style_prompt_modifier(self, style: str) -> str:
        """
        Convert a style key into a ready-to-use system prompt fragment.
        """
        modifiers = {
            "supportive":  "Communicate with deep empathy and emotional validation. Echo the user's feelings and offer genuine comfort.",
            "playful":     "Be witty, warm, and light-hearted. Use gentle humour and keep energy high without being dismissive.",
            "assertive":   "Be direct, confident, and goal-focused. Help the user cut through ambiguity with clarity.",
            "reflective":  "Speak with deliberate depth. Invite introspection. Use questions to deepen the conversation.",
            "neutral":     "",  # no modifier — default persona
        }
        return modifiers.get(style, "")

    # ── Training internals ─────────────────────────────────────────────────────

    def _ppo_update(self):
        states    = torch.stack(self.buffer.states)
        actions   = torch.tensor(self.buffer.actions, dtype=torch.long)
        old_lps   = torch.tensor(self.buffer.log_probs, dtype=torch.float32)
        returns   = self.buffer.compute_returns()

        # Normalise returns
        returns = (returns - returns.mean()) / (returns.std() + 1e-8)

        for _ in range(4):  # PPO epochs
            logits, values = self.model(states)
            probs  = torch.softmax(logits, dim=-1)
            dist   = torch.distributions.Categorical(probs)
            new_lps = dist.log_prob(actions)

            # Ratio and clipped objective
            ratio       = torch.exp(new_lps - old_lps)
            surr1       = ratio * returns
            surr2       = torch.clamp(ratio, 1 - CLIP_RATIO, 1 + CLIP_RATIO) * returns
            actor_loss  = -torch.min(surr1, surr2).mean()

            # Value loss
            critic_loss = F.mse_loss(values.squeeze(-1), returns)

            # Entropy bonus (encourages exploration)
            entropy_bonus = dist.entropy().mean()

            loss = actor_loss + 0.5 * critic_loss - 0.01 * entropy_bonus

            self.optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 0.5)
            self.optimizer.step()

    def _load_if_exists(self):
        if os.path.exists(MODEL_PATH):
            try:
                ckpt = torch.load(MODEL_PATH, weights_only=True)
                self.model.load_state_dict(ckpt)
                print(f"[PPO] Loaded checkpoint from {MODEL_PATH}")
            except Exception as e:
                print(f"[PPO] Checkpoint load failed — starting fresh. ({e})")

    def _save(self):
        try:
            torch.save(self.model.state_dict(), MODEL_PATH)
        except Exception as e:
            print(f"[PPO] Checkpoint save failed: {e}")


# ── Singleton ──────────────────────────────────────────────────────────────────
_ppo_instance: PPOPolicy | None = None

def get_ppo_policy() -> PPOPolicy:
    global _ppo_instance
    if _ppo_instance is None:
        _ppo_instance = PPOPolicy()
    return _ppo_instance

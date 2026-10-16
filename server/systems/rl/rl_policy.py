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
import json
import time
import torch
import torch.nn.functional as F
from typing import Dict

from .model import PPOModel, encode_state, select_action
from .reward import compute_reward
from .store import get_transition_store

# ── Action space ───────────────────────────────────────────────────────────────
ACTION_STYLE_MAP = {
    0: "supportive",
    1: "playful",
    2: "assertive",
    3: "reflective",
    4: "neutral",
}

MODEL_PATH = os.path.join(os.path.dirname(__file__), "ppo_checkpoint.pt")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


# ── Hyperparameters ────────────────────────────────────────────────────────────
GAMMA       = 0.99   # Discount factor
CLIP_RATIO  = 0.2    # PPO clip threshold
LR          = 3e-4
TRAIN_EVERY = 16     # Update model every N turns
N_STEP      = _env_int("AARIYA_RL_N_STEP", 4)   # n-step return horizon

# Corpus retraining (Track E): retrain on the durable transition log when this
# many NEW transitions have accrued and at least RL_RETRAIN_HOURS have elapsed
# since the last checkpoint. Real transitions only.
RL_RETRAIN_MIN_NEW = _env_int("AARIYA_RL_RETRAIN_MIN_TRANSITIONS", 200)
RL_RETRAIN_HOURS   = _env_float("AARIYA_RL_RETRAIN_HOURS", 24.0)
_CORPUS_LIMIT      = 2000


def _n_step_returns(rewards, values, dones, n_step: int = N_STEP,
                    gamma: float = GAMMA) -> torch.Tensor:
    """n-step TD returns with a value bootstrap at the horizon.

    A terminal step inside the window stops it (no bootstrap); running off the
    end of the buffer falls back to a partial, un-bootstrapped return. `values[i]`
    must be V(s_i). Uses real stored values only — no fabricated targets.
    """
    T = len(rewards)
    returns = [0.0] * T
    for t in range(T):
        G = 0.0
        horizon = -1
        for k in range(n_step):
            i = t + k
            if i >= T:
                break
            G += (gamma ** k) * rewards[i]
            horizon = k + 1
            if dones[i]:
                horizon = -1   # terminal inside the window → no bootstrap
                break
        if horizon >= 0:
            h = t + horizon
            if h < T:
                G += (gamma ** horizon) * values[h]
        returns[t] = G
    return torch.tensor(returns, dtype=torch.float32)


class RolloutBuffer:
    """Stores experiences for one PPO update cycle."""
    def __init__(self):
        self.states:      list[torch.Tensor] = []
        self.actions:     list[int]          = []
        self.log_probs:   list[float]        = []
        self.rewards:     list[float]        = []
        self.values:      list[float]        = []
        self.next_states: list[torch.Tensor] = []
        self.dones:       list[bool]         = []

    def push(self, state, action, log_prob, reward, value,
             next_state=None, done: bool = False):
        self.states.append(state)
        self.actions.append(action)
        self.log_probs.append(log_prob)
        self.rewards.append(reward)
        self.values.append(value)
        self.next_states.append(next_state if next_state is not None else state)
        self.dones.append(bool(done))

    def compute_returns(self, n_step: int = N_STEP, gamma: float = GAMMA):
        """n-step discounted returns for the collected rollout."""
        return _n_step_returns(self.rewards, self.values, self.dones, n_step, gamma)

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

        self._last_action   = action  # type: ignore[assignment]
        self._last_log_prob = lp
        self._last_value    = value
        self._last_state    = state_tensor

        return ACTION_STYLE_MAP[action]  # type: ignore[index]

    def observe_outcome(self, prev_context: Dict, curr_context: Dict,
                        meta: Dict | None = None) -> float:
        """
        Record the result of the last turn.
        Should be called AFTER the user has responded.

        `meta` may carry `user_id`, `session_id`, and `done` (terminal turn)
        so the durable transition log is attributed and long-horizon returns
        can respect episode boundaries.

        Returns the computed reward scalar.
        """
        if self._last_state is None:
            return 0.0

        reward = compute_reward(prev_context, curr_context)
        next_state = encode_state(curr_context)
        done = bool((meta or {}).get("done", False))

        self.buffer.push(
            state      = self._last_state,
            action     = self._last_action,
            log_prob   = self._last_log_prob,
            reward     = reward,
            value      = self._last_value,
            next_state = next_state,
            done       = done,
        )

        # Persist the real transition (durable long-horizon corpus). A failure
        # here must never break the conversation turn.
        try:
            get_transition_store().record(
                state      = self._last_state.tolist(),
                action     = self._last_action,
                reward     = reward,
                next_state = next_state.tolist(),
                done       = done,
                user_id    = (meta or {}).get("user_id", "user_default"),
                session_id = (meta or {}).get("session_id"),
            )
        except Exception as e:
            print(f"[PPO] transition persist failed: {e}")

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

    def _run_ppo(self, states, actions, old_lps, returns):
        """One PPO optimisation pass over prepared tensors."""
        if returns.numel() > 1:
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

    def _ppo_update(self):
        states    = torch.stack(self.buffer.states)
        actions   = torch.tensor(self.buffer.actions, dtype=torch.long)
        old_lps   = torch.tensor(self.buffer.log_probs, dtype=torch.float32)
        returns   = self.buffer.compute_returns()
        self._run_ppo(states, actions, old_lps, returns)

    # ── Long-horizon corpus retraining (Track E) ───────────────────────────────

    def _last_train_ts(self) -> float:
        """mtime of the last checkpoint (0.0 when none exists yet)."""
        try:
            return os.path.getmtime(MODEL_PATH) if os.path.exists(MODEL_PATH) else 0.0
        except OSError:
            return 0.0

    def _train_from_rows(self, rows) -> int:
        """One PPO update over a REAL transition corpus.

        Old log-probs/values are re-evaluated under the current model (a valid
        on-policy snapshot at the start of the update); returns use the stored
        real rewards + terminal flags. Returns the number of rows used.
        """
        states, actions, rewards, dones = [], [], [], []
        for r in rows:
            try:
                states.append(json.loads(r["state_json"]))
            except (json.JSONDecodeError, TypeError, KeyError):
                continue
            actions.append(int(r["action"]))
            rewards.append(float(r["reward"]))
            dones.append(bool(r["done"]))
        if len(states) < 2:
            return 0

        s_t = torch.tensor(states, dtype=torch.float32)
        a_t = torch.tensor(actions, dtype=torch.long)
        with torch.no_grad():
            logits, values = self.model(s_t)
            old_lps = torch.distributions.Categorical(logits=logits).log_prob(a_t)
        returns = _n_step_returns(rewards, values.squeeze(-1).tolist(), dones, N_STEP, GAMMA)
        self._run_ppo(s_t, a_t, old_lps, returns)
        return len(states)

    def maybe_retrain_from_corpus(self, min_new_transitions=None,
                                  min_interval_seconds=None) -> bool:
        """Retrain from the durable transition log when enough NEW rows accrued.

        Returns True iff an update ran (and the checkpoint was written). Never
        fabricates data: a fresh DB with too few rows returns False.
        """
        store = get_transition_store()
        min_new = RL_RETRAIN_MIN_NEW if min_new_transitions is None else int(min_new_transitions)
        min_interval = (RL_RETRAIN_HOURS * 3600) if min_interval_seconds is None else float(min_interval_seconds)

        try:
            total = store.count()
        except Exception as e:
            print(f"[PPO] corpus count failed: {e}")
            return False
        if total < min_new:
            return False

        last_train = self._last_train_ts()
        if last_train and (time.time() - last_train) < min_interval:
            return False
        new_since = store.count_since(last_train) if last_train else total
        if new_since < min_new:
            return False

        rows = store.recent(limit=max(min_new, _CORPUS_LIMIT))
        if self._train_from_rows(rows):
            self._save()
            return True
        return False

    def get_status(self) -> Dict:
        """Status for GET /api/rl/status — reflects real store + checkpoint state."""
        store = get_transition_store()
        dist = {style: 0 for style in ACTION_STYLE_MAP.values()}
        actions, total = [], 0
        try:
            actions = store.latest_actions(limit=200)
            total = store.count()
        except Exception:
            pass
        for a in actions:
            style = ACTION_STYLE_MAP.get(a)
            if style:
                dist[style] += 1
        last_train = self._last_train_ts()
        return {
            "trained": os.path.exists(MODEL_PATH),
            "checkpoint_path": MODEL_PATH,
            "transitions": total,
            "recent_actions": len(actions),
            "last_train_ts": last_train or None,
            "last_train_age_seconds": (round(time.time() - last_train, 1) if last_train else None),
            "buffer_size": len(self.buffer),
            "n_step": N_STEP,
            "action_distribution": dist,
        }

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

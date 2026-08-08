import torch
import torch.nn as nn

class PPOModel(nn.Module):
    """
    Actor-Critic network for Proximal Policy Optimization (PPO).
    Takes an encoded state and evaluates probabilities for distinct
    conversational behavior styles (Action Space) alongside a Value baseline.
    """
    def __init__(self, state_dim=5, num_actions=5):
        super().__init__()

        # Shared feature extractor
        self.shared = nn.Sequential(
            nn.Linear(state_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 64),
            nn.ReLU()
        )

        # Policy head (Actor) - outputs logits for behavior actions
        self.policy_head = nn.Linear(64, num_actions)
        
        # Value head (Critic) - estimates expected return
        self.value_head = nn.Linear(64, 1)

    def forward(self, x):
        """
        x: tensor of shape (batch, state_dim)
        Returns: logits of shape (batch, num_actions), values of shape (batch, 1)
        """
        x = self.shared(x)
        logits = self.policy_head(x)
        value = self.value_head(x)
        return logits, value

def encode_state(context: dict) -> torch.Tensor:
    """
    Converts conversation context back into a standardized tensor.
    Expects keys: valence, arousal, trust, contradiction, history_len
    """
    # Defensive fallbacks for missing keys
    val = context.get("valence", 0.0)
    aro = context.get("arousal", 0.5)
    tru = context.get("trust", 0.5)
    cnt = context.get("contradiction", 0.0)
    hlen = context.get("history_len", 0.0) / 50.0  # Normalize

    return torch.tensor([val, aro, tru, cnt, hlen], dtype=torch.float32)

def select_action(model: PPOModel, state_tensor: torch.Tensor):
    """
    Sample an action stochastically from the model's categorical distribution.
    """
    with torch.no_grad():
        logits, value = model(state_tensor.unsqueeze(0))
        probs = torch.softmax(logits, dim=-1)
        dist = torch.distributions.Categorical(probs)
        action = dist.sample()
        
    return action.item(), dist.log_prob(action).item(), value.item()

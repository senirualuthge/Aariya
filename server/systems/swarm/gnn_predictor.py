"""
Graph Neural Network Prediction Engine (Agents Swarm Visualize §241).

A practical, dependency-light temporal graph predictor (GraphSAGE-style
message passing + GRU) built on plain PyTorch — no torch_geometric required.

    nodes = agents (features: [vx, vy, x, y])
    edges = interactions (influence / distance / communication)
    predicts next state of the swarm (x, y per agent)

The model learns to predict next-frame positions from current positions,
velocities, and graph structure. `SwarmGNN` is the module; `GNNPredictor`
is the training/inference facade that works on plain dict agents.
"""

from typing import Any, Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn


class SAGEConv(nn.Module):
    """Minimal SAGE-style convolution: h_v = W · (h_v + mean(h_neighbors))."""

    def __init__(self, in_dim: int, out_dim: int):
        super().__init__()
        self.linear = nn.Linear(in_dim, out_dim)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
        # aggregate neighbor mean
        src, dst = edge_index
        agg = torch.zeros_like(x)
        agg.index_add_(0, dst, x[src])
        counts = torch.zeros(x.size(0), device=x.device).scatter_add_(
            0, dst, torch.ones(dst.size(0), device=x.device)
        )
        counts = counts.clamp(min=1)
        agg = agg / counts.unsqueeze(1)
        return self.linear(x + agg)


class SwarmGNN(nn.Module):
    def __init__(self, in_dim: int = 4, hidden: int = 64, out_dim: int = 2):
        super().__init__()
        self.conv1 = SAGEConv(in_dim, hidden)
        self.conv2 = SAGEConv(hidden, hidden)
        self.rnn = nn.GRU(hidden, hidden, batch_first=True)
        self.out = nn.Linear(hidden, out_dim)

    def forward(self, x: torch.Tensor, edge_index: torch.Tensor,
                seq: Optional[torch.Tensor] = None) -> torch.Tensor:
        x = torch.relu(self.conv1(x, edge_index))
        x = torch.relu(self.conv2(x, edge_index))
        x, _ = self.rnn(x.unsqueeze(0))
        x = x.squeeze(0)
        return self.out(x)


class GNNPredictor:
    """Training/inference facade over dict-based swarm agents."""

    def __init__(self, in_dim: int = 4, hidden: int = 64, lr: float = 1e-3,
                 seed: int = 0):
        torch.manual_seed(seed)
        self.model = SwarmGNN(in_dim=in_dim, hidden=hidden, out_dim=2)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=lr)
        self.loss_fn = nn.MSELoss()
        self.trained = False

    @staticmethod
    def build_edges(agents: List[Dict[str, Any]], threshold: float = 20.0) -> torch.Tensor:
        """Connect agents within `threshold` distance (undirected edges)."""
        n = len(agents)
        src, dst = [], []
        for i in range(n):
            for j in range(i + 1, n):
                dx = agents[i].get("x", 0.0) - agents[j].get("x", 0.0)
                dy = agents[i].get("y", 0.0) - agents[j].get("y", 0.0)
                if (dx * dx + dy * dy) < threshold * threshold:
                    src += [i, j]
                    dst += [j, i]
        return torch.tensor([src, dst], dtype=torch.long)

    @staticmethod
    def _features(agents: List[Dict[str, Any]]) -> torch.Tensor:
        return torch.tensor(
            [[a.get("vx", 0.0), a.get("vy", 0.0), a.get("x", 0.0), a.get("y", 0.0)]
             for a in agents],
            dtype=torch.float,
        )

    @staticmethod
    def _targets(agents: List[Dict[str, Any]]) -> torch.Tensor:
        return torch.tensor(
            [[a.get("x", 0.0), a.get("y", 0.0)] for a in agents], dtype=torch.float
        )

    def train_step(self, agents: List[Dict[str, Any]],
                   targets: List[Dict[str, Any]]) -> float:
        """One gradient step: predict next positions from current state."""
        self.model.train()
        x = self._features(agents)
        edges = self.build_edges(agents)
        y = self._targets(targets)
        self.optimizer.zero_grad()
        pred = self.model(x, edges)
        loss = self.loss_fn(pred, y)
        loss.backward()
        self.optimizer.step()
        self.trained = True
        return float(loss.item())

    @torch.no_grad()
    def predict(self, agents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Predict next (x, y) for every agent."""
        self.model.eval()
        if not agents:
            return []
        x = self._features(agents)
        edges = self.build_edges(agents)
        pred = self.model(x, edges)
        pred = pred.numpy()
        return [
            {"id": a.get("id", i),
             "x": round(float(pred[i, 0]), 3),
             "y": round(float(pred[i, 1]), 3),
             "confidence": round(float(self._conf(pred[i])), 3)}
            for i, a in enumerate(agents)
        ]

    @staticmethod
    def _conf(v: "np.ndarray") -> float:
        """0.5..1 heuristic — small deltas are more confident."""
        return float(max(0.5, min(1.0, 1.0 - float(np.abs(v).sum()) / 20.0)))

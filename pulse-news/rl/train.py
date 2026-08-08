"""Offline RL training pipeline — reads from replay buffer + dataset logs."""
from __future__ import annotations

import json
import os
import sys

import torch
import torch.optim as optim

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from model.dqn import DQN
from memory.replay_buffer import ReplayBuffer

BATCH_SIZE = 64
GAMMA = 0.95
EPOCHS = 1000
DATASET_PATH = os.path.join(os.path.dirname(__file__), "dataset", "logs.jsonl")


def main():
    buffer = ReplayBuffer(capacity=100000, path=os.path.join(os.path.dirname(__file__), "buffer_train"))
    if os.path.exists(DATASET_PATH):
        with open(DATASET_PATH) as f:
            for line in f:
                d = json.loads(line)
                buffer.push(d["state"], d["action"], d["reward"], d["next_state"])
        print(f"Loaded {len(buffer)} transitions from dataset")
    else:
        print("No dataset found — training from buffer only")
        return

    model = DQN()
    optimizer = optim.Adam(model.parameters(), lr=0.001)

    for epoch in range(EPOCHS):
        if len(buffer) < BATCH_SIZE:
            break
        states, actions, rewards, next_states = buffer.sample(BATCH_SIZE)

        s = torch.tensor(states, dtype=torch.float32)
        ns = torch.tensor(next_states, dtype=torch.float32)
        r = torch.tensor(rewards, dtype=torch.float32)
        a = torch.tensor(actions, dtype=torch.long)

        q_values = model(s)
        next_q = model(ns).detach()

        target = q_values.clone()
        for i in range(BATCH_SIZE):
            target[i][a[i]] = r[i] + GAMMA * float(torch.max(next_q[i]))

        loss = ((q_values - target) ** 2).mean()
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if epoch % 50 == 0:
            print(f"Epoch {epoch}, Loss {loss.item():.6f}")

    torch.save(model.state_dict(), os.path.join(os.path.dirname(__file__), "trained_dqn.pt"))
    print("Model saved")


if __name__ == "__main__":
    main()

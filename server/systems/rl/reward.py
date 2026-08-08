def compute_reward(prev_state: dict, curr_state: dict) -> float:
    """
    Calculates the RL scaler reward based on how the user's state shifted 
    after the AI took a specific action.
    
    Expected keys:
    - valence
    - trust
    - continued (bool indicating if engagement survived the turn)
    """
    reward = 0.0

    # 1. Emotional Improvement (Valence shifted towards positive)
    p_val = prev_state.get("valence", 0.0)
    c_val = curr_state.get("valence", 0.0)
    reward += (c_val - p_val) * 2.0

    # 2. Trust Gain
    p_tru = prev_state.get("trust", 0.5)
    c_tru = curr_state.get("trust", 0.5)
    reward += (c_tru - p_tru) * 3.0

    # 3. Continued Engagement vs Drop-off
    continued = curr_state.get("continued", True)
    if continued:
        reward += 2.0
    else:
        reward -= 2.0

    return reward

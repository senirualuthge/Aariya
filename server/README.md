# Python Brain Server - AI Girl

## Overview

The Python Brain server is the cognitive core of the AI Girl project. It handles:

- **Memory Management**: Short-term and long-term memory storage
- **Personality Evolution**: Dynamic personality drift based on user interactions
- **Session Tracking**: User session analytics and metrics
- **WebSocket Communication**: Real-time bidirectional communication with clients

## Setup

### Requirements

```bash
pip install -r requirements.txt
```

Requires:

- Python 3.10+
- FastAPI 0.100.0+
- uvicorn 0.23.0+
- pydantic 2.0.0+
- websockets 11.0+

### Database Initialization

The database is automatically initialized on server startup. It creates:

- `~/.aariya/data.db` on Linux/Mac
- `C:\Users\<username>\.aariya\data.db` on Windows

Manual initialization:

```bash
python -m server.db
```

### Running the Server

```bash
# From project root
uvicorn server.main:app --host 0.0.0.0 --port 8000 --reload
```

Options:

- `--reload`: Auto-reload on code changes (dev only)
- `--host 0.0.0.0`: Listen on all interfaces
- `--port 8000`: Server port

## WebSocket Protocol

### Endpoint

```
ws://localhost:8000/ws/brain
```

### Client → Server Messages

#### 1. Lifecycle Ping

```json
{
  "lifecycle": "ping",
  "timestamp": 1234567890
}
```

Response:

```json
{
  "type": "pong"
}
```

#### 2. Connection Event

```json
{
  "type": "input.multimodal",
  "timestamp": 1234567890,
  "lifecycle": "connect"
}
```

#### 3. Text Message

```json
{
  "type": "input.multimodal",
  "timestamp": 1234567890,
  "text": "Hello, how are you?",
  "lifecycle": "update"
}
```

#### 4. Multimodal Input (Vision + Text)

```json
{
  "type": "input.multimodal",
  "timestamp": 1234567890,
  "text": "I'm feeling happy!",
  "vision": {
    "face_detected": true,
    "emotion": { "happy": 0.8, "surprised": 0.2 }
  },
  "lifecycle": "update"
}
```

### Server → Client Messages

#### State Update

```json
{
  "type": "state.update",
  "brain_state": {
    "personality": {
      "warmth": 0.5,
      "energy": 0.5,
      "assertiveness": 0.5,
      "formality": 0.5
    },
    "emotion_target": {
      "neutral": 1.0
    },
    "thought_process": "Processing sensory input (Python Brain Active)"
  },
  "response_text": "I heard you say: 'Hello, how are you?'. Processing through Python Brain...",
  "meta": {
    "timestamp": 1234567890.123,
    "session_id": "abc123...",
    "received_vision": false,
    "received_text": true,
    "recent_memories": 3
  }
}
```

## Personality Drift Algorithm

The Brain implements an **Exponential Moving Average (EMA)** algorithm for personality evolution:

### Personality Axes

- **Warmth** (-0.4 to 0.6): Friendliness and emotional openness
- **Energy** (0.2 to 0.8): Activity level and enthusiasm
- **Assertiveness** (0.2 to 0.7): Confidence and directness
- **Formality** (0.3 to 0.8): Conversation style

### Update Mechanism

Updates occur **weekly** (7 days between snapshots):

```python
# Calculate target values from session data (last 7 days)
warmth_target = 0.6 * avg_valence + 0.4 * (1 - avg_volatility)
energy_target = avg_arousal
assertiveness_target = 1 - avg_volatility
formality_target = current_formality  # Stable

# Apply EMA update (alpha = 0.01 for slow drift)
warmth_new = (1 - 0.01) * warmth_current + 0.01 * warmth_target
energy_new = (1 - 0.01) * energy_current + 0.01 * energy_target
# ... same for other axes
```

### Session Metrics

- **avg_valence**: Average emotional positivity (-1 to 1)
- **avg_arousal**: Average activation/energy (0 to 1)
- **valence_volatility**: Emotional stability (std dev)

**Example:**

- User is consistently positive → warmth increases
- User is energetic → energy increases
- User is volatile/unpredictable → assertiveness decreases

## Testing

### Quick Test

```bash
# Terminal 1: Start server
uvicorn server.main:app --host localhost --port 8000

# Terminal 2: Run test client
python test_client.py
```

### Interactive CLI

```bash
python interactive_client.py
```

Type messages and see:

- Personality state after each exchange
- Memory count
- Session tracking

## Database Schema

### Tables

- `users`: User profiles and session counts
- `sessions`: Detailed session metrics
- `personality_snapshots`: Historical personality evolution
- `memories`: Short-term and long-term memory storage

Query examples:

```sql
-- View recent personality evolution
SELECT timestamp, warmth, energy, assertiveness
FROM personality_snapshots
WHERE user_id = 'user_default'
ORDER BY timestamp DESC LIMIT 10;

-- View session history
SELECT session_id, start_time, duration_sec, avg_valence
FROM sessions
ORDER BY start_time DESC LIMIT 5;
```

## Future Enhancements

- [ ] LLM integration for intelligent responses
- [ ] Voice emotion analysis from audio data
- [ ] Multi-user support with authentication
- [ ] Advanced memory retrieval (semantic search)
- [ ] Real-time emotion tracking and response adaptation

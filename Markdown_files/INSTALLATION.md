# Fixv2 Installation & Setup Guide

## Prerequisites

- Python 3.9+
- Node.js 16+ (for client-side)
- (Optional) Redis 6+
- (Optional) PostgreSQL 13+

> **Note**: Redis and PostgreSQL are optional. The system will automatically fall back to in-memory storage (Redis) and SQLite (PostgreSQL) for development.

## Installation Steps

### 1. Install Python Dependencies

```bash
cd "D:\Code Base\AI Girl\server"
pip install -r requirements.txt
```

**Dependencies installed:**

- FastAPI & Uvicorn (web server)
- Pydantic (data validation)
- psycopg2-binary (PostgreSQL driver)
- redis (Redis client)
- tensorflow (neural network - optional)
- numpy (numerical operations)

### 2. Run Database Migrations

```bash
python -m migrations
```

**Expected output:**

```
[OK] PostgreSQL connection pool initialized
[MIGRATION] Found 1 pending migrations
[OK] Migration 001_add_trust_and_contradiction applied successfully
[SUMMARY] Applied 1 migrations
```

### 3. Start the Server

```bash
python main.py
```

**Expected output:**

```
{"timestamp": "2026-02-12T13:30:00Z", "service": "ai-girl-brain", "level": "INFO", "message": "Database initialized"}
{"timestamp": "2026-02-12T13:30:00Z", "service": "ai-girl-brain", "level": "INFO", "message": "Database migrations completed"}
{"timestamp": "2026-02-12T13:30:00Z", "service": "ai-girl-brain", "level": "INFO", "message": "Default user initialized"}
{"timestamp": "2026-02-12T13:30:00Z", "service": "ai-girl-brain", "level": "INFO", "message": "All Fixv2 systems initialized"}
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

### 4. Verify Installation

**Check health endpoint:**

```bash
curl http://localhost:8000/health
```

**Expected response:**

```json
{
  "status": "healthy",
  "version": "2.0.0-fixv2",
  "redis": true,
  "postgres": true
}
```

## Configuration

### Environment Variables

Create a `.env` file in `server/` directory:

```env
# Redis Configuration (optional)
REDIS_HOST=localhost
REDIS_PORT=6379

# PostgreSQL Configuration (optional)
DATABASE_URL=postgresql://user:password@localhost:5432/aigirl

# Server Configuration
HOST=0.0.0.0
PORT=8000
```

### Production Setup

For production deployment:

1. **Set up Redis:**

   ```bash
   # Install Redis
   sudo apt-get install redis-server

   # Start Redis
   sudo systemctl start redis
   ```

2. **Set up PostgreSQL:**

   ```bash
   # Install PostgreSQL
   sudo apt-get install postgresql

   # Create database
   sudo -u postgres createdb aigirl
   ```

3. **Configure environment:**

   ```bash
   export DATABASE_URL="postgresql://user:password@localhost:5432/aigirl"
   export REDIS_HOST="localhost"
   export REDIS_PORT=6379
   ```

4. **Run migrations:**

   ```bash
   python -m migrations
   ```

5. **Start server with production settings:**
   ```bash
   uvicorn server.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```

## Testing

### Manual Testing

**Test WebSocket connection:**

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/brain");

ws.onopen = () => {
  console.log("Connected");

  // Send test message
  ws.send(
    JSON.stringify({
      lifecycle: "connect",
      text: "Hello!",
      vision: {
        face_valence: 0.5,
        face_arousal: 0.3,
        face_confidence: 0.8,
        voice_valence: 0.4,
        voice_arousal: 0.2,
        voice_confidence: 0.7,
        text_sentiment: 0.6,
        text_confidence: 0.9,
      },
    }),
  );
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Received:", data);
  console.log("Trust:", data.meta.trust);
  console.log("State:", data.meta.trust_tier);
  console.log("Contradiction:", data.meta.contradiction_ema);
};
```

**Test compliance endpoints:**

```bash
# Export user data
curl "http://localhost:8000/api/compliance/export-user-data?user_id=user_default"

# Get personality profile
curl "http://localhost:8000/api/compliance/personality-profile?user_id=user_default"
```

## Troubleshooting

### Issue: "Redis connection failed"

**Solution:** This is expected if Redis is not installed. The system will automatically fall back to in-memory storage.

**To fix (optional):**

```bash
# Install Redis
pip install redis

# Or use Docker
docker run -d -p 6379:6379 redis:latest
```

### Issue: "PostgreSQL connection failed"

**Solution:** This is expected if PostgreSQL is not installed. The system will automatically fall back to SQLite.

**To fix (optional):**

```bash
# Install PostgreSQL driver
pip install psycopg2-binary

# Set DATABASE_URL
export DATABASE_URL="postgresql://user:password@localhost:5432/aigirl"
```

### Issue: "TensorFlow not installed"

**Solution:** This is expected. The neural policy network will use heuristic fallback.

**To fix (optional):**

```bash
# Install TensorFlow
pip install tensorflow==2.15.0
```

### Issue: Migration errors

**Solution:** Check database permissions and ensure tables don't already exist.

**Rollback migration:**

```bash
# Manually run rollback script
sqlite3 ~/.aariya/data.db < server/migrations/001_add_trust_and_contradiction_rollback.sql
```

## Next Steps

1. **Client Integration**: Update React client to use new trust/contradiction metrics
2. **Neural Network Training**: Collect data and train the policy network
3. **Performance Tuning**: Optimize database queries and caching
4. **Monitoring**: Set up log aggregation and alerting

## Support

For issues or questions, refer to:

- [Implementation Plan](file:///C:/Users/senir/.gemini/antigravity/brain/a09fce24-f97c-46e6-863a-86dcca746fb2/implementation_plan.md)
- [Walkthrough](file:///C:/Users/senir/.gemini/antigravity/brain/a09fce24-f97c-46e6-863a-86dcca746fb2/walkthrough.md)
- [Task Breakdown](file:///C:/Users/senir/.gemini/antigravity/brain/a09fce24-f97c-46e6-863a-86dcca746fb2/task.md)

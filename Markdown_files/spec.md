# Pulse AI News — Product Specification
> Version 1.0 | Status: Pre-Build

---

## 1. Product Vision

**Pulse AI News** is an autonomous, real-time AI news intelligence platform. It continuously monitors global news streams, detects what matters before it goes mainstream, and delivers personalized, voice-capable briefings to the user.

> **Core promise:** Know what's important before everyone else — hands-free, noise-free.

---

## 2. Problem Statement

| Problem | Current Reality | What Pulse Solves |
|---|---|---|
| News overload | Hundreds of articles per hour | AI filters to top 3–5 meaningful events |
| Slow detection | User discovers news reactively | System detects emergence before it peaks |
| Context-free headlines | "Market fell" | "Market dropped 3% — tech sell-off driven by AI regulation" |
| Platform fragmentation | Multiple apps, manual checking | Single unified feed + push + voice |
| Manual effort | User must read to understand | Auto-summary, auto-read, voice control |

---

## 3. Target Users

- Knowledge workers who can't afford to miss high-impact events
- Investors, researchers, analysts monitoring specific domains
- People who want to stay informed but have limited time

---

## 4. Core Intelligence Principles

### Importance is NOT popularity
A story is important when it is:
- **Accelerating** (velocity spike, not just volume)
- **Diverse** (multiple independent sources, not one viral tweet)
- **Novel** (semantic distance from known history)
- **Credible** (source trust-weighted confirmation)

### Ranking Formula
```
T(t) = w₁·V(t) + w₂·G(t) + w₃·E(t) + w₄·N(t) + w₅·D(t)

V(t) = mention velocity (dM/dt)
G(t) = engagement (clicks + shares + citations)
E(t) = entity spread (# distinct real-world actors)
N(t) = novelty = 1 - cosine_similarity(embedding, historical_clusters)
D(t) = source diversity entropy = -Σ pᵢ log pᵢ
```

### Breaking News Detection
```
B(t) = α·Anomaly(t) + β·Velocity(t) + γ·SourceDiversity(t) + δ·Novelty(t) + ε·Credibility(t)

Alert triggers when: P(B=1 | X) > 0.85
```

---

## 5. System Architecture

### 5-Layer Stack

```
┌─────────────────────────────────────────────────────┐
│  SOURCES: NewsAPI, GDELT, Reddit, RSS, Twitter/X    │
└─────────────────────────┬───────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│  INGESTION: Kafka / Redis Streams                   │
│  • Deduplication (content hash)                     │
│  • Cleaning & normalization                         │
│  • Rate limiting per source                         │
└─────────────────────────┬───────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│  PROCESSING: NLP Pipeline                           │
│  • Embeddings (sentence-transformers)               │
│  • Entity extraction (spaCy)                        │
│  • Topic clustering (BERTopic)                      │
│  • Sentiment + velocity computation                 │
└─────────────────────────┬───────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│  INTELLIGENCE: ML + Agent Layer                     │
│  • Trend forecasting (XGBoost + TFT ensemble)       │
│  • Anomaly detection (z-score + EWMA)               │
│  • Multi-agent editorial board                      │
│  • Breaking news Bayesian scorer                    │
└─────────────────────────┬───────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│  USER LAYER: Flutter App + Voice + Push             │
│  • Real-time feed via WebSocket                     │
│  • Firebase push notifications                      │
│  • TTS auto-reader with scroll sync                 │
│  • Conversational news assistant (RAG)              │
└─────────────────────────────────────────────────────┘
```

---

## 6. Multi-Agent Editorial Board

| Agent | Objective | Model Type |
|---|---|---|
| **Trend Agent** | "Will this become important in the next 6–24h?" | TFT + XGBoost ensemble |
| **Fact Agent** | "Is this reliable? Any contradictions?" | Cross-encoder + LLM verifier |
| **Narrative Agent** | "What does this mean in plain language?" | GPT-class LLM (RAG-grounded) |
| **Graph Agent** | "How does this connect to other events?" | Knowledge graph + PageRank |
| **Alert Agent** | "Should the user be notified right now?" | Rule engine + ML gating |
| **Orchestrator** | Coordinates all agents, produces final report | Priority fusion layer |

### Agent Output Fusion
```python
final_score = (
    0.45 * trend_score
  + 0.35 * credibility_score
  + 0.20 * novelty_score
)

publish_if: final_score > threshold
         AND source_diversity > threshold
         AND fact_conflicts == resolved
```

---

## 7. Data Model (Postgres + pgvector)

### Core Tables
```sql
sources          -- RSS feeds, APIs, publishers (with credibility_score)
articles         -- Raw news items (immutable, with hash for dedup)
article_chunks   -- Split articles for RAG
embeddings       -- VECTOR(1536) with HNSW index
entities         -- Named entities (people, orgs, locations)
topics           -- BERTopic clusters
trend_signals    -- Per-topic velocity, engagement, novelty per timestamp
trend_snapshots  -- Aggregated time windows (1m / 5m / 1h)
trend_predictions-- ML forecast output (probability + expected peak time)
users            -- User accounts
user_interactions-- Clicks, saves, dismissals (personalization signal)
user_topic_prefs -- Per-user topic interest scores
event_stream     -- Kafka ingestion buffer (JSONB)
```

### Vector Index
```sql
CREATE EXTENSION vector;
CREATE INDEX embedding_idx ON embeddings
USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

---

## 8. Kafka Topic Architecture

```
news.raw.ingest         ← all raw articles from all sources
news.cleaned.article    ← deduplicated, normalized
news.cleaned.chunked    ← split into RAG chunks
news.nlu.entities       ← extracted named entities
news.nlu.topics         ← BERTopic cluster assignments
news.embedding.chunk    ← vectorized chunks
news.trend.signals      ← per-topic velocity / novelty signals
news.trend.snapshots    ← aggregated windows
news.trend.predictions  ← ML breaking probability + peak forecast
news.alerts             ← confirmed breaking events
user.events             ← click / dismiss user feedback
system.dlq              ← dead letter queue
```

---

## 9. ML Forecasting Model

### Architecture (Hybrid Ensemble)
```
final_trend_score =
    0.4 × XGBoost(tabular_features)
  + 0.4 × TFT(time_series_per_topic)
  + 0.2 × embedding_novelty_score
```

### Feature Groups

| Group | Features |
|---|---|
| **Temporal** | 1h/6h/24h velocity, acceleration |
| **Engagement** | clicks, shares, citations (normalized per source) |
| **Semantic** | article embedding, topic centroid embedding, novelty score |
| **Graph** | entity degree centrality, PageRank, clustering coefficient |
| **Source** | credibility score, domain authority, political neutrality |

### Label Construction
```python
# Future attention volume over horizon H
y(t) = Σ M(t') for t' in [t, t+H]
label = 1 if y(t) > percentile(90) else 0

# Time-safe split (NO random split)
Train:  days 1–80
Val:    days 81–90
Test:   days 91–100
```

### Evaluation Metrics
- **NDCG@K** — primary ranking quality
- **MAP** — mean average precision
- **Lead time** = `time_detected - time_peak` (detect BEFORE peak)
- **MAE / RMSE** — attention volume prediction

---

## 10. RAG Pipeline (Conversational Layer)

```
User Query
  ↓ Query embedding
  ↓ Hybrid retrieval: vector search + full-text + trend_score boost
  ↓ Reranking: cross-encoder (bge-reranker) OR LLM scoring
  ↓ Context assembly: top 5–20 chunks, grouped by article, deduplicated
  ↓ Temporal weighting: W(t) = e^(-λΔt)  (recent news weighted higher)
  ↓ LLM generation with citations + contradiction detection
  ↓ Structured answer
```

---

## 11. Real-Time Performance Budget

| Stage | Target Latency |
|---|---|
| Ingestion | 20–50ms |
| Feature extraction | 50–100ms |
| Embedding lookup (HNSW) | 1–5ms |
| Graph update | 50ms |
| Bayesian scoring | 10–20ms |
| **Total (hot path)** | **< 500ms** |
| LLM validation | Async (non-blocking) |

### Key Optimizations
- Pre-embed all chunks, cache in Redis (never compute in hot path)
- Incremental feature updates: `V(t) = V(t-1) + delta`
- HNSW index for approximate nearest neighbor
- LLM = validation/generation layer only (not decision maker)

---

## 12. User Interface — "Pulse AI News"

### Screens

#### Home Feed
- Categorized sections: 🔥 Breaking / 📈 Economy / 🤖 Tech / 🌍 Global
- Cards: title, AI summary, source, impact tag, time ago
- Color-coded urgency (red = critical, amber = high, grey = low)

#### Breaking Alert Popup
- Auto-triggered by alert engine
- Voice announcement: *"Heads up — major AI regulation announced..."*
- Options: **Read Now** | **Dismiss**

#### Article Reader
- Auto-scrolls synchronized to TTS speech speed
- Current sentence highlighted
- Stops on manual scroll or voice "stop"
- Controls: ▶️ Play / ⏸ Pause / ⏹ Stop / ⏩ Next

#### Voice Command Layer
| Command | Action |
|---|---|
| "What happened today?" | Load top 5 headlines |
| "Any major tech news?" | Filter by tech category |
| "Read the top story" | Open + start TTS reader |
| "Stop reading" | Stop TTS |
| "Next article" | Advance to next item |

#### Trends Screen
- Topic velocity chart (% change / 24h)
- Emerging / Peaking / Decaying classification

#### Settings
- Interest categories (multi-select)
- Region filter
- Risk mode (threats/crashes only)
- Alert frequency & severity threshold

---

## 13. Push Notification System

```
Backend → importance > 8 detected
       → Firebase Admin SDK sends push
       → Flutter firebase_messaging receives
       → Show system notification or in-app alert popup
       → User taps → opens ArticleScreen with relevant article
```

---

## 14. Personalization Engine

### Feedback Signals
- Views, clicks, saves, shares, dismissals, dwell time

### Adaptive Ranking
```python
importance_score += user_interest_weight × topic_affinity

# Online learning update:
model_weight += learning_rate × user_feedback_error
```

### User Preference Store
```python
user_prefs = {
    "interests": ["AI", "economy", "startups"],
    "region": "Asia",
    "risk_mode": True,
    "alert_threshold": 7,  # 1-10 importance minimum
    "alert_cooldown_mins": 30
}
```

---

## 15. Anti-Spam / Alert Quality Rules

| Rule | Implementation |
|---|---|
| Minimum importance threshold | `importance >= alert_threshold (default 7)` |
| Alert cooldown | 30-minute cooldown per topic after alert |
| Source diversity gate | Must have ≥ 2 independent sources |
| Fact confidence gate | `fact_confidence > 0.6` before alerting |
| Deduplication | Content hash + semantic similarity check |
| Group similar alerts | Cluster near-duplicate events into one card |

---

## 16. Tech Stack

| Layer | Technology |
|---|---|
| Backend API | FastAPI (Python) |
| Streaming | Kafka → Redis Streams (MVP fallback) |
| NLP | spaCy, sentence-transformers, BERTopic |
| Vector DB | Qdrant (production) / FAISS (MVP) |
| ML Models | XGBoost / LightGBM + TFT (PyTorch) |
| LLM | GPT-4.1-mini / GPT-4.1 via OpenAI API |
| Background Jobs | APScheduler / Celery |
| Database | PostgreSQL + pgvector |
| Frontend | Flutter (Dart) |
| Voice TTS | flutter_tts (local) → ElevenLabs (premium) |
| Voice STT | speech_to_text Flutter plugin |
| Push | Firebase Cloud Messaging |
| Monitoring | OpenTelemetry + Prometheus |

---

## 17. MVP Scope (What to Build First)

> MVP goal: "Smart news chatbot + real-time top stories feed with voice reader"

### In MVP
- [x] NewsAPI + GDELT ingestion (polling, 5-min interval)
- [x] GPT-based summarization + importance scoring
- [x] Simple velocity metric (sliding window mention counter)
- [x] FAISS local vector store for RAG
- [x] Basic RAG conversational assistant
- [x] Flutter home screen + article reader with TTS
- [x] WebSocket live feed
- [x] Firebase push notifications (high importance only)
- [x] User preferences (interests, risk mode)

### Deferred to Production
- [ ] Kafka streaming infrastructure
- [ ] Full multi-agent editorial board
- [ ] TFT + XGBoost ML ensemble
- [ ] BERTopic + spaCy NLP pipeline
- [ ] Qdrant vector cluster
- [ ] Graph Agent + knowledge graph
- [ ] Online learning / personalization
- [ ] Sub-500ms latency optimization
- [ ] Multi-region / geo-filtering
- [ ] OpenTelemetry observability

---

## 18. Known Risks

| Risk | Mitigation |
|---|---|
| Hallucinated importance (LLM over-rates story) | Statistical scoring as primary; LLM as validation only |
| False breaking alerts | Multi-gate rule: velocity + source diversity + fact confidence |
| API rate limits (NewsAPI, Twitter) | Rotating keys, exponential backoff, Kafka buffer |
| LLM cost at scale | GPT-4.1-mini for classification; full model for generation only |
| misinformation amplification | Fact agent cross-verification before publishing |

---

*Spec condensed from `New News Teller.txt` — 7,411 lines → clean architecture document*

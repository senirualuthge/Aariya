# Technical Analysis

This document provides a deep technical breakdown of the stack, libraries, patterns, and design methodologies employed across the AI Girl project.

## Technology Stack

### Backend
- **Framework**: FastAPI (Python) - Chosen for native asynchronous capabilities and WebSocket support.
- **Event Bus**: Redis (v4.6.0+) - Utilized heavily via Streams and Pub/Sub for the Cognitive Event Bus, allowing high-throughput, decoupled messaging between systems.
- **Database (Primary/Auth)**: PostgreSQL - Used for strong consistency transactional data.
- **Database (Cognitive/Local)**: SQLite - Used for persistent history, reflections, and localized memory storage, making agent states easy to snapshot and backup.
- **Runtime Scheduler**: Built on Python `asyncio`, utilizing priority queues to manage task execution, retries, and task interruption gracefully.
- **Metrics & Environment**: Relies on `psutil` and dynamic state tracking within the `WorldModel`.

### Frontend
- **Framework**: React 18, Vite.
- **State Management**: Zustand - Preferred over Redux for minimal boilerplate and real-time updates.
- **Asset/Avatar Rendering**: WebGL wrappers handling Avatar Animation and LipSync.

## Architectural Patterns

### Executive Intelligence Layer (EIL)
The system eschews monolithic planning for a hierarchical EIL. An `AttentionManager` scores all incoming bus events (0-100 scale). If an event breaches an urgency threshold, the `ExecutiveController` preempts the `RuntimeScheduler` to redirect focus.

### Critical Thinking Engine (CTE)
Instead of piping raw LLM outputs to capabilities, reasoning is staged. The CTE breaks down inputs via `HypothesisGenerator`, challenges them via `Counterargument`, verifies facts via `FactChecker`, and scores them via `Confidence`. This ensures high-fidelity, hallucination-resistant autonomous operations.

### World Model over Direct APIs
The AI does not blindly execute tools. It queries the `WorldModel`—a constantly updating reflection of `desktop`, `browser`, `people`, and `environment` states—to understand its context before acting.

### Strict Capability SDK
All executable tools are unified under `server.sdk.capability.Capability`. Capabilities must provide a schema, define their exact permissions, and implement `.health_check()` before the `RuntimeScheduler` will execute them.

## Technical Debt & Considerations
1. **Migration to 19-Folder Architecture**: 60+ legacy subsystem folders were recently archived to `_legacy_archive/` to enforce the strict 19-folder structure. Some legacy code inside this archive may still be relied upon by older UI components and requires modernization.
2. **Redis Dependency**: The core nervous system strictly relies on Redis Streams. If Redis goes down, the Cognitive Event Bus halts. Fallback mechanisms (like in-memory queues) are not currently prioritized.

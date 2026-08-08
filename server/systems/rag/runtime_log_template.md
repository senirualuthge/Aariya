# Aariya Runtime Log — Template

This vault records Aariya's **running details** — episodic logs written by
Aariya herself. The developer vault (`second-brain`) holds codebase context;
this runtime vault holds how Aariya is actually running.

## Entry format

Every entry is a `##` section appended to the daily file `Logs/<YYYY-MM-DD>.md`:

    ## <Type> — HH:MM:SS
    <content>

Example (Telemetry):

    ## Telemetry — 14:40:35
    - Server uptime: 3h 12m
    - System uptime: 69h 38m
    - Memory: 64.7% used (7.3 GB of 16.0 GB), server RSS 145 MB
    - CPU: 20.6%
    - Active agents: 16 (PlannerAgent, VisionAgent, ...)
    - Obsidian vaults: 5184 developer / 3 runtime chunks

## Entry types

- **Telemetry** — scheduled live system metrics (server/systems/rag/runtime_telemetry.py)
- **Research** — research-agent turns: question + answer excerpt (server/systems/agent/controller.py)
- **Maintenance / Heartbeat** — ad-hoc operational notes

## Notes

- Keep lines under ~160 chars; use `- ` bullets for key-value data.
- Files are chunked on `##` headers — one entry ≈ one retrievable chunk, so
  keep entries self-contained (a reader should understand one entry alone).
- Do not delete this template; it documents the format for Aariya and for
  anyone reading the logs.

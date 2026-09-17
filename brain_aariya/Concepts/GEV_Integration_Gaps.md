# GEV Integration Gaps

## 1. Agent Registry Wiped by GEVAgent Startup (Registration Bug)
**Location:** `server/main.py` (around line 151)
**Issue:** `GEVAgent` is manually injected into the agent registry on startup using `reg.update_from_scan([rec])`. 
Because `update_from_scan` treats the passed array as the *complete* list of all currently active agents, passing an array containing *only* `GEVAgent` causes the registry to mark all other auto-discovered agents (from the `AgentWatcher`) as absent (`absent_scans` incremented). If the app restarts multiple times before a full scan completes, this permanently removes all other agents from the system dashboard.
**Fix:** Provide a dedicated method like `register_static_agent(rec)` in `agent_registry.py` that bypasses the absence-incrementing logic, or include `GEVAgent` automatically within the `AgentScanner` results.

## 2. Double Polling (WebSocket Duplication)
**Location:** `server/systems/gev/gev_agent.py` and `server/routers/gev_router.py`
**Issue:** We have duplicated polling loops firing every 30 seconds:
- `GEVAgent._poll_loop` calls `get_gev_client().snapshot()` and writes the data to `WorldState`.
- `gev_router.py` (`_stream_loop`) independently calls `get_gev_client().snapshot()` and fans the data out to WebSocket clients.
This double-polls the GEV proxy API (`localhost:4173`).
**Fix:** `gev_router.py` should not poll the API directly. It should either read from `WorldState` when it detects an update, or `GEVAgent` should trigger an event payload that the router fans out to clients, effectively unifying the pipeline.

## 3. Potential Synthetic Data in God's Eye View Backend
**Location:** `gods-eye-view/src/data/flights.js`, `gods-eye-view/src/data/militaryFlights.js`, `gods-eye-view/vite.config.js`
**Issue:** The user specified: "replace the mock, synthetic, hardcoded data with real data." While the Python proxy `gev_client.py` strictly returns real data (or `{"available": False}`), the GEV frontend/data logic has interpolation logic (`synthesizeForwardKinematicsFix`) creating "synthetic" data points to guess aircraft locations between updates. Additionally, `vite.config.js` builds synthetic CCTV SVGs as fallbacks.
**Fix:** Verify if these kinematic extrapolations and visual placeholders violate the strict "real data only" mandate and replace them if necessary.

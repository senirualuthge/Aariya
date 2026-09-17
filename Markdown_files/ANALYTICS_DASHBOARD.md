# Analytics Dashboard Documentation

## Overview
The **Analytics Dashboard** (`src/components/AnalyticsDashboard.jsx`) is a frontend React component that serves as a real-time, slide-out telemetry panel for the AI Girl application. It provides developers and users with direct visibility into the AI's long-term memory, emotional continuity, and personality drift over time.

## Architecture & Integration

### Placement
The dashboard is mounted in `src/App.jsx` at the root of the application, inside the `.canvas-container`. This ensures it overlays the 3D Avatar (Three.js/Experience) without interfering with the rendering pipeline.

### State Management
The dashboard relies on two primary state sources:
1. **Local Component State (`useState`):** Manages the visibility toggle (`show`) and the data fetched from the database (`sessions`, `personalityHistory`, `currentMetrics`).
2. **Global Zustand Store (`useStore`):** Pulls the *current, real-time* personality variables (`personality`, `personalityPreset`) directly from the active runtime.

### Data Polling
The component utilizes a polling mechanism inside a `useEffect` hook. When the dashboard is open (`show === true`), it queries the local SQLite database (`getDB()`) every **5 seconds** (5000ms) to ensure the visual metrics reflect the latest session and drift data instantly.

## Database Queries & Data Sources
The dashboard reads directly from the `~/.aariya/data.db` SQLite database using `better-sqlite3`. It targets the `user_default` profile and executes three primary read operations:

1. **Recent Sessions:** Queries the `sessions` table (Limits to the last 10 entries) to get timestamp, duration, ECS, and PSI.
2. **Personality Drift History:** Queries the `personality_snapshots` table (Limits to the last 20 entries) to track shifts in Warmth, Energy, Assertiveness, and Formality.
3. **Current Aggregated Metrics:** Executes aggregations (`COUNT`, `AVG`, `SUM`) on the `sessions` table to compute lifetime interaction statistics.

---

## UI Components & Metrics Explained

The dashboard is divided into four main visual sections:

### 1. Current Stats
Displays lifetime metrics aggregated across all sessions.
* **Total Sessions:** The total number of times the user has interacted with the avatar.
* **Avg ECS (Emotional Continuity Score):** A score (0-100) indicating the stability of the avatar's emotional state over time.
* **Avg PSI (Personality Satisfaction Index):** A metric (-1 to +1) indicating how well the AI's behaviors align with the user's interactions.
* **Total Time:** The aggregate time (converted to minutes) spent interacting with the AI.

### 2. Personality
Visualizes the AI's current personality state in real-time.
* **Preset Display:** Shows the active personality archetype (e.g., `SHY`, `BUBBLY`, `CALM`).
* **Axis Progress Bars:** Four horizontal gradient bars mapping the exact coordinates of the personality matrix:
  * **Warmth:** -1.0 to 1.0 (Cold to Warm)
  * **Energy:** 0.0 to 1.0 (Calm to Energetic)
  * **Assertiveness:** 0.0 to 1.0 (Passive to Assertive)
  * **Formality:** 0.0 to 1.0 (Casual to Formal)

### 3. Recent Sessions
A chronological log of the last 5 interactions. Each row displays:
* The timestamp of the session.
* The ECS and PSI recorded for that specific session.
* The total duration in seconds.

### 4. Personality Drift (Last 20 Snapshots)
A vertical bar chart visualization that proves the Exponential Moving Average (EMA) algorithm is functioning. 
* It graphs the historical trajectory of **Warmth** (Pink) and **Energy** (Cyan) over the last 20 database snapshots.
* This allows the user to visually see the AI "adapting" and drifting as it learns from long-term interactions.

---

## Styling & Theming (`AnalyticsDashboard.css`)

The UI is built with a cyber-aesthetic, emphasizing translucency and neon accents.

* **Toggle Button:** Fixed to the top-right (`top: 20px; right: 20px;`), styled with a black translucent background and a cyan (`#00f2ff`) border.
* **Dashboard Panel:** 
  * Fixed to the right edge of the screen with `width: 400px`.
  * Features a dark glassmorphic background (`rgba(0, 0, 0, 0.95)`).
  * Uses a smooth CSS `@keyframes slideIn` animation for entry.
  * Employs custom styled Webkit scrollbars.
* **Data Visualizations:** 
  * Metric cards use a subtle cyan background tint (`rgba(0, 242, 255, 0.1)`).
  * Progress bars utilize a `linear-gradient(90deg, #ff8fa3, #00f2ff)` to visually distinguish the axes.
  * Drift charts use vertical height scaling applied dynamically via inline React styles (`style={{height: ...}}`).

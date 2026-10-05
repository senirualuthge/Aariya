/**
 * @module dvrTimeline
 * @description DVR Timeline Scrubber — interactive playback control for the
 * GEV globe.  Connects to the backend /api/gev/timeline and /api/gev/playback
 * endpoints to let users scrub through historical snapshots.
 *
 * UI:
 *   A bottom-docked bar with a range slider, play/pause, speed controls,
 *   and timestamp readouts.  Glows with the GEV sci-fi aesthetic.
 *
 * Power-saving:
 *   The scrubber only fetches data when the user actively scrubs or presses
 *   play.  No background polling — it reads from the agent's in-memory
 *   timeline ring buffer.
 */

const TIMELINE_POLL_MS = 30_000; // Refresh timeline metadata every 30 s
const PLAYBACK_STEP_MS = 10_000; // Default: jump 10 s per auto-play tick

// ── DOM construction ─────────────────────────────────────────────────────────

function buildDOM() {
  const root = document.createElement('div');
  root.id = 'dvr-timeline';
  root.className = 'dvr-timeline hidden';
  root.setAttribute('role', 'region');
  root.setAttribute('aria-label', 'DVR Timeline Scrubber');
  root.innerHTML = `
    <div class="dvr-timeline-inner">
      <div class="dvr-left">
        <button class="dvr-btn dvr-toggle-btn" id="dvr-toggle" title="Toggle DVR Timeline (T)">
          <span class="dvr-icon">⏱</span>
          <span class="dvr-label">DVR</span>
        </button>
        <div class="dvr-playback-controls">
          <button class="dvr-btn dvr-transport" id="dvr-rewind" title="Rewind 30s (←)">⏪</button>
          <button class="dvr-btn dvr-transport dvr-play-btn" id="dvr-play" title="Play/Pause (Space)">▶</button>
          <button class="dvr-btn dvr-transport" id="dvr-forward" title="Forward 30s (→)">⏩</button>
        </div>
      </div>

      <div class="dvr-center">
        <div class="dvr-timestamp-row">
          <span class="dvr-timestamp" id="dvr-current-time">--:--:--</span>
          <span class="dvr-separator">/</span>
          <span class="dvr-timestamp dvr-total" id="dvr-total-range">--:--:--</span>
        </div>
        <div class="dvr-slider-wrap">
          <input type="range" class="dvr-slider" id="dvr-slider"
                 min="0" max="100" step="0.1" value="100"
                 aria-label="DVR timeline scrubber" />
          <div class="dvr-tick-marks" id="dvr-tick-marks"></div>
        </div>
        <div class="dvr-meta-row">
          <span class="dvr-meta" id="dvr-snapshot-count">0 snapshots</span>
          <span class="dvr-meta" id="dvr-buffer-status">Buffer: --</span>
        </div>
      </div>

      <div class="dvr-right">
        <div class="dvr-speed-control">
          <span class="dvr-speed-label">SPEED</span>
          <select class="dvr-speed-select" id="dvr-speed" aria-label="Playback speed">
            <option value="0.5">0.5×</option>
            <option value="1" selected>1×</option>
            <option value="2">2×</option>
            <option value="4">4×</option>
          </select>
        </div>
        <button class="dvr-btn dvr-live-btn" id="dvr-live" title="Jump to live">
          <span class="dvr-live-dot"></span>
          LIVE
        </button>
      </div>
    </div>
  `;
  return root;
}

// ── Time formatting ──────────────────────────────────────────────────────────

function formatTime(ts) {
  if (!Number.isFinite(ts)) return '--:--:--';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0s';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

// ── DvrTimeline class ───────────────────────────────────────────────────────

export class DvrTimeline {
  /**
   * @param {object} options
   * @param {string} [options.apiUrl='/api/gev'] — GEV backend base URL
   */
  constructor({ apiUrl = '/api/gev' } = {}) {
    this._apiUrl = apiUrl;
    this._root = null;
    this._slider = null;
    this._playBtn = null;
    this._liveBtn = null;
    this._speedSelect = null;
    this._timeLabel = null;
    this._totalLabel = null;
    this._countLabel = null;
    this._bufferLabel = null;

    // Timeline data
    this._snapshots = [];       // { timestamp, snapshot }[]
    this._oldestTs = null;
    this._newestTs = null;
    this._currentIndex = -1;
    this._isPlaying = false;
    this._playTimer = null;
    this._playSpeed = 1;
    this._pollTimer = null;
    this._visible = false;

    // Callbacks
    this._onSnapshotCallback = null;

    // Keyboard bindings
    this._keyHandler = this._onKey.bind(this);
  }

  // ── Lifecycle ──────────────────────────────────────────────────────────────

  init() {
    if (this._root) return;
    this._root = buildDOM();
    document.body.appendChild(this._root);

    // Cache DOM refs
    this._slider = this._root.querySelector('#dvr-slider');
    this._playBtn = this._root.querySelector('#dvr-play');
    this._liveBtn = this._root.querySelector('#dvr-live');
    this._speedSelect = this._root.querySelector('#dvr-speed');
    this._timeLabel = this._root.querySelector('#dvr-current-time');
    this._totalLabel = this._root.querySelector('#dvr-total-range');
    this._countLabel = this._root.querySelector('#dvr-snapshot-count');
    this._bufferLabel = this._root.querySelector('#dvr-buffer-status');

    // Event listeners
    this._root.querySelector('#dvr-toggle').addEventListener('click', () => this.toggle());
    this._root.querySelector('#dvr-rewind').addEventListener('click', () => this.rewind(30));
    this._root.querySelector('#dvr-forward').addEventListener('click', () => this.forward(30));
    this._playBtn.addEventListener('click', () => this.togglePlay());
    this._liveBtn.addEventListener('click', () => this.jumpToLive());
    this._speedSelect.addEventListener('change', () => {
      this._playSpeed = parseFloat(this._speedSelect.value) || 1;
    });

    this._slider.addEventListener('input', () => {
      this._scrubToSlider();
    });

    // Keyboard shortcuts
    document.addEventListener('keydown', this._keyHandler);

    console.log('[DVR] Timeline initialized');
  }

  destroy() {
    this.stop();
    document.removeEventListener('keydown', this._keyHandler);
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
    if (this._root) {
      this._root.remove();
      this._root = null;
    }
    console.log('[DVR] Timeline destroyed');
  }

  // ── Visibility ─────────────────────────────────────────────────────────────

  show() {
    this._visible = true;
    if (this._root) this._root.classList.remove('hidden');
    this._startPolling();
  }

  hide() {
    this._visible = false;
    this.stop();
    if (this._root) this._root.classList.add('hidden');
    this._stopPolling();
  }

  toggle() {
    if (this._visible) this.hide();
    else this.show();
  }

  // ── Data fetching ──────────────────────────────────────────────────────────

  async _fetchTimeline() {
    try {
      const params = new URLSearchParams();
      if (this._oldestTs) params.set('since_ts', String(this._oldestTs));
      params.set('limit', '360');

      const r = await fetch(`${this._apiUrl}/timeline?${params}`);
      if (!r.ok) return false;
      const data = await r.json();

      this._snapshots = data.data || [];
      this._oldestTs = data.oldest;
      this._newestTs = data.newest;

      this._updateUI();
      return true;
    } catch (e) {
      console.warn('[DVR] Timeline fetch error:', e);
      return false;
    }
  }

  async _fetchPlayback(targetTs) {
    try {
      const r = await fetch(`${this._apiUrl}/playback?target_ts=${targetTs}`);
      if (!r.ok) return null;
      const data = await r.json();
      return data.data || null;
    } catch (e) {
      console.warn('[DVR] Playback fetch error:', e);
      return null;
    }
  }

  // ── Scrubbing ──────────────────────────────────────────────────────────────

  _scrubToSlider() {
    if (!this._snapshots.length || !this._slider) return;

    const pct = parseFloat(this._slider.value);
    const index = Math.round((pct / 100) * (this._snapshots.length - 1));
    this._setIndex(index);
  }

  async _setIndex(index) {
    if (index < 0 || index >= this._snapshots.length) return;
    this._currentIndex = index;

    const entry = this._snapshots[index];
    if (!entry) return;

    this._timeLabel.textContent = formatTime(entry.timestamp);
    this._slider.value = this._snapshots.length > 1
      ? (index / (this._snapshots.length - 1)) * 100
      : 100;

    // Notify the globe to apply this snapshot
    if (this._onSnapshotCallback) {
      this._onSnapshotCallback(entry.snapshot, entry.timestamp);
    }
  }

  // ── Transport controls ─────────────────────────────────────────────────────

  togglePlay() {
    if (this._isPlaying) this.pause();
    else this.play();
  }

  play() {
    if (this._isPlaying) return;
    this._isPlaying = true;
    this._playBtn.textContent = '⏸';
    this._playBtn.title = 'Pause (Space)';

    // If at the end, jump to start
    if (this._currentIndex >= this._snapshots.length - 1) {
      this._currentIndex = 0;
    }

    this._tick();
    console.log('[DVR] Playing at', this._playSpeed, '×');
  }

  pause() {
    this._isPlaying = false;
    this._playBtn.textContent = '▶';
    this._playBtn.title = 'Play (Space)';
    if (this._playTimer) {
      clearTimeout(this._playTimer);
      this._playTimer = null;
    }
    console.log('[DVR] Paused');
  }

  stop() {
    this.pause();
    this._currentIndex = -1;
  }

  _tick() {
    if (!this._isPlaying) return;

    const nextIndex = this._currentIndex + 1;
    if (nextIndex >= this._snapshots.length) {
      this.pause();
      return;
    }

    this._setIndex(nextIndex);

    // Schedule next tick based on interval between snapshots
    let delay = PLAYBACK_STEP_MS / this._playSpeed;
    if (this._currentIndex < this._snapshots.length - 1) {
      const currentTs = this._snapshots[this._currentIndex]?.timestamp || 0;
      const nextTs = this._snapshots[this._currentIndex + 1]?.timestamp || currentTs;
      const gap = (nextTs - currentTs) * 1000; // ms
      if (gap > 0) delay = Math.max(100, gap / this._playSpeed);
    }

    this._playTimer = setTimeout(() => this._tick(), delay);
  }

  rewind(seconds = 30) {
    if (!this._snapshots.length) return;
    const targetTs = (this._snapshots[this._currentIndex]?.timestamp || this._newestTs || 0) - seconds;
    this._findAndSetClosest(targetTs);
  }

  forward(seconds = 30) {
    if (!this._snapshots.length) return;
    const targetTs = (this._snapshots[this._currentIndex]?.timestamp || this._newestTs || 0) + seconds;
    this._findAndSetClosest(targetTs);
  }

  _findAndSetClosest(targetTs) {
    if (!this._snapshots.length) return;
    let bestIdx = 0;
    let bestDist = Infinity;
    for (let i = 0; i < this._snapshots.length; i++) {
      const dist = Math.abs(this._snapshots[i].timestamp - targetTs);
      if (dist < bestDist) {
        bestDist = dist;
        bestIdx = i;
      }
    }
    this._setIndex(bestIdx);
  }

  jumpToLive() {
    this.pause();
    if (this._snapshots.length) {
      this._setIndex(this._snapshots.length - 1);
    }
  }

  // ── UI updates ─────────────────────────────────────────────────────────────

  _updateUI() {
    if (!this._root) return;

    const count = this._snapshots.length;
    this._countLabel.textContent = `${count} snapshot${count !== 1 ? 's' : ''}`;

    if (this._oldestTs && this._newestTs) {
      const span = this._newestTs - this._oldestTs;
      this._totalLabel.textContent = formatTime(this._newestTs);
      this._bufferLabel.textContent = `Buffer: ${formatDuration(span)}`;
    }

    // Update tick marks
    this._updateTickMarks();

    // If at the end (live position), auto-follow
    if (this._currentIndex === -1 || this._currentIndex >= count - 1) {
      this._currentIndex = count - 1;
      if (count > 0) {
        this._timeLabel.textContent = formatTime(this._snapshots[count - 1].timestamp);
        this._slider.value = 100;
      }
    }
  }

  _updateTickMarks() {
    const container = this._root.querySelector('#dvr-tick-marks');
    if (!container) return;
    container.innerHTML = '';

    const count = this._snapshots.length;
    if (count < 2) return;

    // Show one tick per ~30 seconds of data
    const span = (this._newestTs || 0) - (this._oldestTs || 0);
    const tickInterval = Math.max(1, Math.floor(count / Math.min(count, Math.ceil(span / 30))));

    for (let i = 0; i < count; i += tickInterval) {
      const tick = document.createElement('div');
      tick.className = 'dvr-tick';
      const pct = count > 1 ? (i / (count - 1)) * 100 : 0;
      tick.style.left = `${pct}%`;
      tick.title = formatTime(this._snapshots[i].timestamp);
      container.appendChild(tick);
    }
  }

  // ── Keyboard ───────────────────────────────────────────────────────────────

  _onKey(e) {
    // Don't capture when typing in an input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;

    switch (e.key) {
      case ' ':
        if (this._visible) {
          e.preventDefault();
          this.togglePlay();
        }
        break;
      case 'ArrowLeft':
        if (this._visible) {
          e.preventDefault();
          this.rewind(e.shiftKey ? 60 : 30);
        }
        break;
      case 'ArrowRight':
        if (this._visible) {
          e.preventDefault();
          this.forward(e.shiftKey ? 60 : 30);
        }
        break;
      case 't':
      case 'T':
        // Don't toggle if typing
        if (!e.ctrlKey && !e.metaKey && !e.altKey) {
          this.toggle();
        }
        break;
      case 'l':
      case 'L':
        if (this._visible && !e.ctrlKey && !e.metaKey) {
          this.jumpToLive();
        }
        break;
    }
  }

  // ── Polling ────────────────────────────────────────────────────────────────

  _startPolling() {
    if (this._pollTimer) return;
    this._fetchTimeline();
    this._pollTimer = setInterval(() => this._fetchTimeline(), TIMELINE_POLL_MS);
  }

  _stopPolling() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  }

  // ── External API ───────────────────────────────────────────────────────────

  /**
   * Register a callback that receives (snapshot, timestamp) when the
   * user scrubs to a historical point.  The globe should apply this
   * snapshot to update all layers.
   */
  onSnapshot(callback) {
    this._onSnapshotCallback = callback;
  }

  /** Manually refresh the timeline data. */
  async refresh() {
    return this._fetchTimeline();
  }

  /** Get the current playback state. */
  getState() {
    return {
      visible: this._visible,
      playing: this._isPlaying,
      speed: this._playSpeed,
      currentIndex: this._currentIndex,
      snapshotCount: this._snapshots.length,
      currentTimestamp: this._snapshots[this._currentIndex]?.timestamp || null,
      oldest: this._oldestTs,
      newest: this._newestTs,
    };
  }

  /** Get the latest snapshot for the current position. */
  getCurrentSnapshot() {
    if (this._currentIndex < 0 || this._currentIndex >= this._snapshots.length) {
      return null;
    }
    return this._snapshots[this._currentIndex].snapshot;
  }
}

// ── Singleton ─────────────────────────────────────────────────────────────────

let _instance = null;

export function getDvrTimeline() {
  if (!_instance) _instance = new DvrTimeline();
  return _instance;
}

export default DvrTimeline;

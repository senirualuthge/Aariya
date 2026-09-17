import React, { useState, useEffect, useRef, useCallback } from 'react';
import DraggablePanel from './DraggablePanel';
import { apiBase } from '../utils/apiHost';

const API = `${apiBase()}/api/news`;

const CATEGORIES = [
  { key: 'all', label: 'All' },
  { key: 'breaking', label: '🔥 Breaking' },
  { key: 'tech', label: '🤖 Tech' },
  { key: 'economy', label: '📈 Economy' },
  { key: 'global', label: '🌍 Global' },
];

const importanceColor = (imp) => {
  if (imp >= 9) return '#ff4d4d';
  if (imp >= 7) return '#ffb347';
  if (imp >= 5) return '#ffd93d';
  return '#7eb8da';
};

const CATEGORY_META = {
  breaking: { label: '🔥', color: '#ff4d4d' },
  tech: { label: '🤖', color: '#00d9ff' },
  economy: { label: '📈', color: '#ffd93d' },
  global: { label: '🌍', color: '#a8e6cf' },
  security: { label: '🛡', color: '#ff6b6b' },
};

function splitSentences(text) {
  return text
    .replace(/\s+/g, ' ')
    .split(/(?<=[.!?])\s+(?=[A-Z0-9"'“])/)
    .map((s) => s.trim())
    .filter((s) => s.length > 1);
}

function timeAgo(iso) {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (isNaN(t)) return '';
  const mins = Math.max(0, Math.floor((Date.now() - t) / 60000));
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

export default function NewsPanel() {
  const [articles, setArticles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [category, setCategory] = useState('all');
  const [alerts, setAlerts] = useState([]);

  const [selected, setSelected] = useState(null);   // article in reader mode
  const [blocks, setBlocks] = useState([]);          // extracted paragraphs
  const [readingBlocks, setReadingBlocks] = useState([]); // flattened sentence spans
  const [articleLoading, setArticleLoading] = useState(false);

  // Reader / TTS state
  const [reading, setReading] = useState(false);
  const [paused, setPaused] = useState(false);
  const [sentenceIdx, setSentenceIdx] = useState(-1);
  const [rate, setRate] = useState(0.95);

  const contentRef = useRef(null);
  const readerRef = useRef({ token: 0, sentences: [], utterance: null });

  const loadNews = useCallback(async (cat) => {
    setLoading(true);
    setError(null);
    try {
      const url = cat && cat !== 'all' ? `${API}?limit=40&category=${cat}` : `${API}?limit=40`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`News API ${res.status}`);
      const json = await res.json();
      setArticles(json.data || []);
      if (!json.data || !json.data.length) setError('No stories right now — try again in a bit.');
    } catch (e) {
      console.error('[NewsPanel] load failed:', e);
      setError('Could not reach the news feed. Make sure the Aariya server is running.');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadAlerts = useCallback(async () => {
    try {
      const res = await fetch(`${API}/alerts`);
      if (res.ok) {
        const json = await res.json();
        setAlerts(json.data || []);
      }
    } catch (e) {
      /* non-fatal */
    }
  }, []);

  useEffect(() => {
    loadNews(category);
    loadAlerts();
    const t = setInterval(() => loadAlerts(), 60000);
    return () => clearInterval(t);
  }, [category, loadNews, loadAlerts]);

  // ── Open article → fetch full text → prepare reader ─────────────────────────
  const openArticle = async (article, autoRead = false) => {
    stopReading();
    setSelected(article);
    setArticleLoading(true);
    setBlocks([]);
    setReadingBlocks([]);
    try {
      const res = await fetch(`${API}/article?url=${encodeURIComponent(article.url)}`);
      const json = await res.json();
      const raw = (json.data && json.data.blocks) || [];
      setBlocks(raw);
      const sentences = [];
      raw.forEach((para) => {
        splitSentences(para).forEach((s) => sentences.push(s));
      });
      if (!sentences.length && article.description) {
        splitSentences(article.description).forEach((s) => sentences.push(s));
      }
      if (!sentences.length && article.title) {
        sentences.push(article.title);
      }
      readerRef.current.sentences = sentences;
      setReadingBlocks(sentences);
      if (autoRead && sentences.length) startReading(0);
    } catch (e) {
      console.error('[NewsPanel] article load failed:', e);
      const fallback = splitSentences(`${article.title}. ${article.description || ''}`);
      setReadingBlocks(fallback);
      readerRef.current.sentences = fallback;
      if (autoRead && fallback.length) startReading(0);
    } finally {
      setArticleLoading(false);
    }
  };

  // ── Reader / TTS engine ─────────────────────────────────────────────────────
  const stopReading = useCallback(() => {
    readerRef.current.token += 1;
    try {
      window.speechSynthesis.cancel();
    } catch (e) {
      /* noop */
    }
    setReading(false);
    setPaused(false);
    setSentenceIdx(-1);
  }, []);

  const scrollToSentence = (idx) => {
    requestAnimationFrame(() => {
      const el = contentRef.current?.querySelector(`[data-sidx="${idx}"]`);
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  };

  const startReading = useCallback((fromIdx = 0) => {
    const sentences = readerRef.current.sentences;
    if (!sentences || !sentences.length) return;
    stopReading();
    const token = readerRef.current.token;
    setReading(true);
    setPaused(false);

    let idx = fromIdx;
    const step = () => {
      if (readerRef.current.token !== token) return;
      if (idx >= sentences.length) {
        setReading(false);
        setSentenceIdx(-1);
        return;
      }
      setSentenceIdx(idx);
      scrollToSentence(idx);
      const u = new SpeechSynthesisUtterance(sentences[idx]);
      u.rate = rate;
      u.pitch = 1.0;
      u.volume = 1.0;
      u.onend = () => {
        idx += 1;
        step();
      };
      u.onerror = () => {
        if (readerRef.current.token === token) setReading(false);
      };
      readerRef.current.utterance = u;
      try {
        window.speechSynthesis.speak(u);
      } catch (e) {
        setReading(false);
      }
    };
    step();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rate, stopReading]);

  const togglePause = () => {
    if (!reading && !paused) return;
    if (paused) {
      try {
        if (readerRef.current.utterance) {
          window.speechSynthesis.resume();
          setPaused(false);
          return;
        }
      } catch (e) {
        /* fall through to restart */
      }
      startReading(sentenceIdx >= 0 ? sentenceIdx : 0);
    } else {
      try {
        window.speechSynthesis.pause();
        setPaused(true);
      } catch (e) {
        setPaused(true);
      }
    }
  };

  // Manual scroll while reading → pause (user takes over, per spec)
  const onReaderWheel = () => {
    if (reading && !paused) {
      try {
        window.speechSynthesis.pause();
        setPaused(true);
      } catch (e) {
        /* noop */
      }
    }
  };

  // ── Navigation ──────────────────────────────────────────────────────────────
  const gotoNextArticle = () => {
    const list = articles;
    if (!list.length) return;
    const idx = list.findIndex((a) => a.id === selected?.id);
    const next = list[(idx + 1) % list.length];
    if (next && next.id !== selected?.id) openArticle(next, true);
    else startReading(0);
  };

  const backToList = () => {
    stopReading();
    setSelected(null);
    setBlocks([]);
    setReadingBlocks([]);
  };

  const filtered = category === 'all' ? articles : articles.filter((a) => a.category === category);

  // ── Render: headline list ───────────────────────────────────────────────────
  const renderList = () => (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Category tabs */}
      <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', padding: '10px 12px 0' }}>
        {CATEGORIES.map((c) => (
          <button
            key={c.key}
            onClick={() => setCategory(c.key)}
            style={{
              background: category === c.key ? 'linear-gradient(135deg,#ffb3c1,#ff8fa3)' : 'rgba(255,255,255,0.05)',
              color: category === c.key ? '#1a0b12' : '#ffe0e6',
              border: 'none', borderRadius: '20px', padding: '4px 10px',
              fontSize: '0.7rem', cursor: 'pointer', fontWeight: category === c.key ? '700' : '400',
            }}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Alerts strip */}
      {alerts.length > 0 && (
        <div style={{ margin: '8px 12px 0', padding: '6px 10px', borderRadius: '10px', background: 'rgba(255,77,77,0.12)', border: '1px solid rgba(255,77,77,0.3)' }}>
          <div style={{ fontSize: '0.65rem', color: '#ff4d4d', fontWeight: '700', letterSpacing: '1px', marginBottom: '4px' }}>⛔ BREAKING</div>
          {alerts.slice(0, 3).map((a) => (
            <div key={a.id} style={{ fontSize: '0.78rem', padding: '2px 0', cursor: 'pointer', color: '#ffd7d7' }}
              onClick={() => openArticle(a)}>
              {a.title}
            </div>
          ))}
        </div>
      )}

      {/* Headline list */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px 12px' }} className="scrollbar-hide">
        {loading && <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', padding: '40px 0' }}>Loading news…</div>}
        {!loading && error && articles.length === 0 && (
          <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', padding: '30px 8px', fontSize: '0.85rem' }}>
            {error}
            <div style={{ marginTop: '10px' }}>
              <button onClick={() => loadNews(category)} style={refreshBtnStyle}>↻ Retry</button>
            </div>
          </div>
        )}
        {filtered.map((a) => {
          const meta = CATEGORY_META[a.category] || CATEGORY_META.global;
          return (
            <div
              key={a.id}
              onClick={() => openArticle(a)}
              style={{
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid rgba(255,255,255,0.08)',
                borderRadius: '12px', padding: '10px 12px', marginBottom: '8px',
                cursor: 'pointer', transition: 'all 0.2s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(255,143,163,0.12)'; e.currentTarget.style.borderColor = 'rgba(255,143,163,0.3)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; e.currentTarget.style.borderColor = 'rgba(255,255,255,0.08)'; }}
            >
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '4px' }}>
                <span style={{ fontSize: '0.9rem' }}>{meta.label}</span>
                <span style={{ fontSize: '0.65rem', color: 'rgba(255,255,255,0.5)' }}>{a.source}</span>
                <span style={{ marginLeft: 'auto', fontSize: '0.62rem', color: 'rgba(255,255,255,0.4)' }}>{timeAgo(a.published_at)}</span>
              </div>
              <div style={{ fontSize: '0.85rem', fontWeight: '600', color: '#fff', lineHeight: '1.35' }}>{a.title}</div>
              {a.description && (
                <div style={{ fontSize: '0.72rem', color: 'rgba(255,255,255,0.55)', marginTop: '4px', lineHeight: '1.3' }}>
                  {a.description.slice(0, 160)}{a.description.length > 160 ? '…' : ''}
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'center', marginTop: '6px' }}>
                <span style={{ fontSize: '0.6rem', color: importanceColor(a.importance), border: `1px solid ${importanceColor(a.importance)}33`, padding: '1px 8px', borderRadius: '10px', background: `${importanceColor(a.importance)}14` }}>
                  ★ {a.importance}/10
                </span>
                {a.is_risk && (
                  <span style={{ fontSize: '0.6rem', color: '#ff6b6b', marginLeft: '6px' }}>⚠ risk</span>
                )}
                <span style={{ marginLeft: 'auto', fontSize: '0.65rem', color: '#ff8fa3' }}>Read ▸</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );

  // ── Render: article reader ─────────────────────────────────────────────────
  const renderReader = () => {
    const meta = CATEGORY_META[selected?.category] || CATEGORY_META.global;
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Reader toolbar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 12px', borderBottom: '1px solid rgba(255,143,163,0.15)' }}>
          <button onClick={backToList} style={{ ...iconBtnStyle, fontSize: '0.7rem' }}>←</button>
          <div style={{ flex: 1, fontSize: '0.65rem', color: 'rgba(255,255,255,0.4)' }}>{selected?.source}</div>
          <button onClick={() => gotoNextArticle()} style={{ ...iconBtnStyle, fontSize: '0.7rem' }} title="Next article">⏭</button>
        </div>

        {/* Title */}
        <div style={{ padding: '12px 14px 6px' }}>
          <span style={{ fontSize: '0.7rem', color: meta.color }}>{meta.label}</span>
          <h3 style={{ margin: '4px 0 0', fontSize: '1.05rem', color: '#fff', lineHeight: '1.35' }}>{selected?.title}</h3>
        </div>

        {/* Player controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 14px', flexWrap: 'wrap' }}>
          <button onClick={() => (reading || paused ? togglePause() : startReading(0))} style={playBtnStyle}>
            {reading && !paused ? '⏸ Pause' : paused ? '▶ Resume' : '▶ Read Aloud'}
          </button>
          <button onClick={stopReading} style={iconBtnStyle} title="Stop">⏹</button>
          <div style={{ display: 'flex', alignItems: 'center', gap: '4px', marginLeft: 'auto' }}>
            <span style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.5)' }}>⏪</span>
            <input
              type="range" min="0.6" max="1.4" step="0.05" value={rate}
              onChange={(e) => setRate(parseFloat(e.target.value))}
              style={{ width: '70px', accentColor: '#ff8fa3' }}
            />
            <span style={{ fontSize: '0.6rem', color: 'rgba(255,255,255,0.5)' }}>⏩</span>
          </div>
        </div>
        {paused && (
          <div style={{ fontSize: '0.62rem', color: '#ffb347', padding: '0 14px' }}>Paused — scroll or resume to continue.</div>
        )}

        {/* Article content with sentence highlighting */}
        <div
          ref={contentRef}
          onWheel={onReaderWheel}
          onTouchMove={onReaderWheel}
          style={{ flex: 1, overflowY: 'auto', padding: '10px 14px 20px', fontSize: '0.9rem', lineHeight: '1.65' }}
          className="scrollbar-hide"
        >
          {articleLoading && <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', padding: '40px' }}>Fetching article…</div>}
          {!articleLoading && readingBlocks.length === 0 && (
            <div style={{ textAlign: 'center', color: 'rgba(255,255,255,0.4)', padding: '30px' }}>No readable text found on that page.</div>
          )}
          {!articleLoading && blocks.length > 0 && (() => {
            let flatIdx = -1;
            return blocks.map((para, i) => (
              <p key={i} style={{ margin: '0 0 12px', color: 'rgba(255,255,255,0.85)' }}>
                {splitSentences(para).map((s, si) => {
                  flatIdx += 1;
                  const idx = flatIdx;
                  const active = idx === sentenceIdx;
                  return (
                    <span
                      key={`${i}-${si}`}
                      data-sidx={idx}
                      style={{
                        background: active ? 'rgba(255,143,163,0.25)' : 'transparent',
                        borderRadius: active ? '4px' : '0',
                        color: active ? '#fff' : undefined,
                        boxShadow: active ? '0 0 12px rgba(255,143,163,0.35)' : undefined,
                        transition: 'all 0.15s ease',
                      }}
                    >
                      {s}{' '}
                    </span>
                  );
                })}
              </p>
            ));
          })()}
        </div>
      </div>
    );
  };

  return (
    <DraggablePanel
      id="aariya_news"
      defaultPosition={{ x: Math.max(0, window.innerWidth - 460), y: 32 }}
      defaultSize={{ width: '420px', height: '640px' }}
      className="ui-panel chat-panel"
    >
      {/* Header / drag handle */}
      <div className="drag-handle panel-title-bar">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"></path><path d="M18 14h-8"></path><path d="M15 18h-5"></path><path d="M10 6h8v4h-8V6z"></path></svg>
        News Teller
        <button
          onClick={() => loadNews(category)}
          style={{ marginLeft: 'auto', background: 'rgba(255,255,255,0.08)', border: 'none', color: '#ff8fa3', borderRadius: '6px', padding: '2px 8px', fontSize: '0.65rem', cursor: 'pointer' }}
          title="Refresh"
        >
          ↻
        </button>
      </div>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        {selected ? renderReader() : renderList()}
      </div>
    </DraggablePanel>
  );
}

const refreshBtnStyle = {
  background: 'linear-gradient(135deg,#ffb3c1,#ff8fa3)',
  border: 'none', borderRadius: '20px', padding: '6px 18px',
  color: '#1a0b12', fontSize: '0.75rem', fontWeight: '600', cursor: 'pointer',
};

const iconBtnStyle = {
  background: 'rgba(255,255,255,0.08)',
  border: '1px solid rgba(255,255,255,0.12)',
  color: '#ffe0e6', borderRadius: '8px', padding: '4px 10px',
  cursor: 'pointer', fontSize: '0.85rem',
};

const playBtnStyle = {
  background: 'linear-gradient(135deg,#ffb3c1,#ff8fa3)',
  border: 'none', borderRadius: '20px', padding: '5px 16px',
  color: '#1a0b12', fontWeight: '700', fontSize: '0.75rem', cursor: 'pointer',
};

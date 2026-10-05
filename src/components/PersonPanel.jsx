// src/components/PersonPanel.jsx
//
// Person identity side panel (ToDo §4).
//
// Opens when Aariya recognises someone, or when a stranger walks into frame and
// is waiting to be named. Deliberate design points:
//
//  - It never invents an identity. An unmatched face shows as "New person" with
//    a name field; it becomes a profile only when the user submits a name.
//  - Descriptors never reach this component's state or the DOM. The panel takes
//    the profile's human-readable fields only.
//  - "Forget" deletes the profile and its descriptor outright, and there is no
//    way to un-delete it — the privacy-respecting default.

import { useCallback, useEffect, useState } from 'react';
import { useStore } from '../store';
import { IdentityRegistry } from '../systems/personIdentity';
import { apiBase } from '../utils/apiHost';

// One registry per browser session; IdentityRegistry owns its own persistence,
// so the panel and whatever drives the camera agree on who is who.
const registry = new IdentityRegistry();

export { registry as personIdentityRegistry };

function relativeTime(ts) {
  if (!ts) return 'never';
  const seconds = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function StatusDot({ status }) {
  const tone =
    status === 'known' ? 'var(--ai-emotion-happy, #6ee7b7)'
      : status === 'uncertain' ? '#fbbf24'
        : '#94a3b8';
  return (
    <span
      aria-hidden="true"
      style={{
        width: 8, height: 8, borderRadius: '50%',
        background: tone, display: 'inline-block', flex: '0 0 auto',
      }}
    />
  );
}

/**
 * Runs the identification loop for the app: subscribe to descriptors from the
 * face worker, match them against the registry, run the background search for
 * anyone new, and keep the store in sync.
 *
 * Mounted once from main.jsx. Returns nothing; all output is via the store.
 */
export function usePersonIdentification(descriptorSource) {
  const setActivePerson = useStore((s) => s.setActivePerson);
  const setKnownPeople = useStore((s) => s.setKnownPeople);
  const setIdentityEnabled = useStore((s) => s.setIdentityEnabled);
  const setIdentityUnavailable = useStore((s) => s.setIdentityUnavailable);
  const setPersonPanelOpen = useStore((s) => s.setPersonPanelOpen);
  const setPendingEnrollment = useStore((s) => s.setPendingEnrollment);
  const setPeopleContext = useStore((s) => s.setPeopleContext);

  useEffect(() => {
    setKnownPeople(registry.list().map(({ descriptor, ...rest }) => rest));

    const unsubscribeRegistry = registry.subscribe((event) => {
      if (event.type === 'enrolled' || event.type === 'renamed'
        || event.type === 'noted' || event.type === 'cleared') {
        setKnownPeople(registry.list().map(({ descriptor, ...rest }) => rest));
      }
    });

    if (!descriptorSource?.onIdentity) return () => unsubscribeRegistry();

    const offIdentity = descriptorSource.onIdentity(({ descriptor }) => {
      const result = registry.identify(descriptor);
      setIdentityEnabled(true);

      if (result.status === 'new') {
        // Stranger: hold the descriptor in memory only so the panel can enrol
        // it, then start the background search ToDo §4 asks for.
        setActivePerson(null);
        setPendingEnrollment({ descriptor: [...descriptor] });
        setPersonPanelOpen(true);

        registry.searchInBackground(
          { id: `new-${Date.now()}`, name: '' },
          () => fetchPeopleContext(''),
        ).then((context) => {
          if (context?.length) setPeopleContext(context);
        });
        return;
      }

      setPendingEnrollment(null);
      const { descriptor: _drop, ...readable } = result.profile;
      setActivePerson({
        ...readable,
        matchStatus: result.status,
        // Only surface the distance for an uncertain match: "who is this, but
        // confirm first" is useful, "0.31" on a certain match is noise.
        matchDistance: result.status === 'uncertain' ? result.distance : null,
      });
      setPersonPanelOpen(true);
    });

    const offUnavailable = descriptorSource.onIdentityUnavailable?.((reason) => {
      setIdentityUnavailable(reason);
    });

    return () => {
      offIdentity();
      offUnavailable?.();
      unsubscribeRegistry();
    };
  }, [descriptorSource, setActivePerson, setKnownPeople, setIdentityEnabled,
    setIdentityUnavailable, setPersonPanelOpen, setPendingEnrollment, setPeopleContext]);
}

/**
 * Background search for someone Aariya doesn't know yet.
 *
 * Reads the Obsidian vault: the app's own memory of people Aariya has heard
 * about is the most likely place a stranger's name already exists. Failure is
 * non-fatal (searchInBackground swallows it) — a vault miss must not stop the
 * person being named.
 */
async function fetchPeopleContext(name) {
  const base = apiBase();
  const query = name?.trim() || 'people I know';
  const res = await fetch(`${base}/api/obsidian/search?q=${encodeURIComponent(query)}&k=5`);
  if (!res.ok) return null;
  const data = await res.json();
  return Array.isArray(data?.hits) ? data.hits : null;
}

export default function PersonPanel() {
  const open = useStore((s) => s.personPanelOpen);
  const activePerson = useStore((s) => s.activePerson);
  const pending = useStore((s) => s.pendingEnrollment);
  const knownPeople = useStore((s) => s.knownPeople);
  const identityEnabled = useStore((s) => s.identityEnabled);
  const unavailableReason = useStore((s) => s.identityUnavailableReason);
  const peopleContext = useStore((s) => s.peopleContext);
  const setPersonPanelOpen = useStore((s) => s.setPersonPanelOpen);
  const setPendingEnrollment = useStore((s) => s.setPendingEnrollment);

  const [name, setName] = useState('');
  const [notes, setNotes] = useState('');

  const pendingPerson = Boolean(pending?.descriptor);

  useEffect(() => {
    if (pendingPerson) {
      setName('');
      setNotes('');
    }
  }, [pendingPerson]);

  const close = useCallback(() => setPersonPanelOpen(false), [setPersonPanelOpen]);

  const submitEnrolment = useCallback((event) => {
    event.preventDefault();
    if (!pending?.descriptor || !name.trim()) return;
    registry.enroll(pending.descriptor, { name, notes });
    setPendingEnrollment(null);
    setName('');
    setNotes('');
  }, [pending, name, notes, setPendingEnrollment]);

  const saveNote = useCallback((event) => {
    event.preventDefault();
    if (!activePerson?.id || !notes.trim()) return;
    registry.addNote(activePerson.id, notes);
    setNotes('');
  }, [activePerson, notes]);

  const forget = useCallback((id) => {
    registry.forget(id);
    if (activePerson?.id === id) setPersonPanelOpen(false);
  }, [activePerson, setPersonPanelOpen]);

  if (!open) return null;

  return (
    <aside
      className="person-panel"
      aria-label="Person identity"
      style={{
        position: 'fixed',
        right: 16,
        bottom: 96,
        width: 300,
        maxHeight: '60vh',
        overflowY: 'auto',
        background: 'rgba(10, 12, 20, 0.92)',
        border: '1px solid rgba(148, 163, 184, 0.25)',
        borderRadius: 12,
        padding: 14,
        color: '#e2e8f0',
        fontSize: 13,
        zIndex: 1200,
        backdropFilter: 'blur(8px)',
      }}
    >
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <strong style={{ fontSize: 13, letterSpacing: 0.4 }}>WHO IS THIS?</strong>
        <button type="button" onClick={close} aria-label="Close person panel" style={closeBtn}>×</button>
      </header>

      {!identityEnabled && (
        <p style={muted}>
          Identity is off{unavailableReason ? `: ${unavailableReason}` : ''}.
          {' '}Emotion and face detection still work.
        </p>
      )}

      {pendingPerson && (
        <section style={section}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <StatusDot status="new" />
            <span style={{ fontWeight: 600 }}>New person</span>
          </div>
          <p style={muted}>I don\u2019t know this face yet. Name them to remember next time.</p>
          <form onSubmit={submitEnrolment} style={{ display: 'grid', gap: 6 }}>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Name"
              aria-label="Name of new person"
              style={input}
            />
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Notes (optional)"
              aria-label="Notes about new person"
              style={input}
            />
            <button type="submit" disabled={!name.trim()} style={primaryBtn}>Remember this person</button>
          </form>
        </section>
      )}

      {activePerson && (
        <section style={section}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <StatusDot status={activePerson.matchStatus} />
            <span style={{ fontWeight: 600 }}>{activePerson.name}</span>
            {activePerson.matchStatus === 'uncertain' && (
              <span style={{ ...tag, background: 'rgba(251,191,36,0.15)' }}>
                confirm · d={activePerson.matchDistance?.toFixed(2)}
              </span>
            )}
          </div>
          <dl style={dl}>
            <dt>Seen</dt><dd>{activePerson.sightingCount}×</dd>
            <dt>Last seen</dt><dd>{relativeTime(activePerson.lastSeenAt)}</dd>
            <dt>Since</dt><dd>{new Date(activePerson.createdAt).toLocaleDateString()}</dd>
          </dl>
          {activePerson.notes && <p style={muted}>{activePerson.notes}</p>}
          <form onSubmit={saveNote} style={{ display: 'grid', gap: 6 }}>
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Add a note"
              aria-label="Add a note about this person"
              style={input}
            />
            <button type="submit" disabled={!notes.trim()} style={ghostBtn}>Save note</button>
          </form>
          <button type="button" onClick={() => forget(activePerson.id)} style={dangerBtn}>
            Forget this person
          </button>
        </section>
      )}

      {peopleContext?.length > 0 && (
        <section style={section}>
          <div style={sectionTitle}>From the vault</div>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4 }}>
            {peopleContext.map((hit, i) => (
              <li key={hit?.path ?? i} style={muted}>{hit?.title ?? hit?.path ?? 'untitled'}</li>
            ))}
          </ul>
        </section>
      )}

      {knownPeople.length > 0 && (
        <section style={section}>
          <div style={sectionTitle}>Known people · {knownPeople.length}</div>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 4 }}>
            {knownPeople.map((person) => (
              <li key={person.id} style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span>{person.name}</span>
                <span style={muted}>{person.sightingCount}×</span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}

const muted = { color: '#94a3b8', margin: '6px 0', lineHeight: 1.45 };
const section = { borderTop: '1px solid rgba(148,163,184,0.18)', paddingTop: 10, marginTop: 10 };
const sectionTitle = { color: '#94a3b8', fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.6 };
const dl = { display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '2px 10px', margin: '8px 0' };
const tag = { fontSize: 10, padding: '2px 6px', borderRadius: 6 };
const input = {
  background: 'rgba(148,163,184,0.12)', border: '1px solid rgba(148,163,184,0.28)',
  borderRadius: 8, padding: '6px 8px', color: 'inherit', font: 'inherit',
};
const closeBtn = {
  background: 'transparent', border: 0, color: '#94a3b8', fontSize: 18,
  lineHeight: 1, cursor: 'pointer', padding: '0 4px',
};
const primaryBtn = {
  ...input, cursor: 'pointer', background: 'rgba(110,231,183,0.16)',
  borderColor: 'rgba(110,231,183,0.4)', fontWeight: 600,
};
const ghostBtn = { ...input, cursor: 'pointer' };
const dangerBtn = {
  ...input, cursor: 'pointer', marginTop: 8, background: 'rgba(248,113,113,0.12)',
  borderColor: 'rgba(248,113,113,0.35)', color: '#fca5a5',
};
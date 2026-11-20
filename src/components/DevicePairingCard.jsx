// DevicePairingCard — pair THIS computer as a trusted dashboard device.
//
// Pairing needs a one-use code created on the server machine:
//   python -m server.tools.create_device_pairing_code --role dashboard
// The code expires after five minutes and cannot be reused.

import React, { useCallback, useEffect, useState } from 'react';
import { getDeviceIdentity, pairDevice } from '../utils/deviceAuth';

const card = {
  border: '1px solid rgba(0,242,255,0.18)',
  borderRadius: 12,
  padding: '14px 16px',
  background: 'rgba(10,18,32,0.55)',
  display: 'flex',
  flexDirection: 'column',
  gap: 10,
};

const input = {
  background: 'rgba(0,0,0,0.35)',
  border: '1px solid rgba(255,255,255,0.14)',
  borderRadius: 8,
  color: '#e2e8f0',
  padding: '8px 10px',
  fontSize: 13,
  outline: 'none',
};

export default function DevicePairingCard() {
  const [identity, setIdentity] = useState(null);
  const [loading, setLoading] = useState(true);
  const [code, setCode] = useState('');
  const [label, setLabel] = useState('this computer');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setIdentity(await getDeviceIdentity());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const onRequired = () => setIdentity(null);
    window.addEventListener('aariya:device-auth-required', onRequired);
    return () => window.removeEventListener('aariya:device-auth-required', onRequired);
  }, [refresh]);

  const submit = async (event) => {
    event.preventDefault();
    if (!code.trim() || busy) return;
    setBusy(true);
    setError('');
    try {
      await pairDevice({
        pairingCode: code,
        label,
        platform: navigator.platform || 'desktop',
      });
      setDone(true);
      // Reload so every socket asks for a ticket with the new identity.
      setTimeout(() => window.location.reload(), 600);
    } catch (err) {
      setError(err?.message || 'Pairing failed');
    } finally {
      setBusy(false);
    }
  };

  if (loading) return null;

  if (identity) {
    return (
      <div style={{ ...card, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ fontSize: 12, color: 'rgba(226,232,240,0.75)' }}>
          <span style={{ color: '#10b981', fontWeight: 700 }}>● PAIRED</span>
          {'  '}
          {identity.label} · {identity.role} · owner {identity.owner_id}
        </div>
        <div style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>
          device {identity.device_id.slice(0, 8)}
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit} style={card}>
      <div style={{ fontSize: 12, color: 'rgba(226,232,240,0.8)', letterSpacing: 0.4 }}>
        <strong style={{ color: '#ffd93d' }}>PAIR THIS COMPUTER</strong>
        {' — run '}
        <code style={{ color: '#00f2ff' }}>
          python -m server.tools.create_device_pairing_code --role dashboard
        </code>
        {' on the server, then enter the code (valid 5 minutes, one use).'}
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <input
          style={{ ...input, flex: '1 1 150px', letterSpacing: 2, textTransform: 'uppercase' }}
          value={code}
          onChange={(e) => setCode(e.target.value)}
          placeholder="XXXX-XXXX"
          aria-label="Pairing code"
          autoComplete="off"
        />
        <input
          style={{ ...input, flex: '1 1 140px' }}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="device label"
          aria-label="Device label"
        />
        <button
          type="submit"
          disabled={busy || !code.trim()}
          style={{
            ...input,
            cursor: busy || !code.trim() ? 'not-allowed' : 'pointer',
            color: '#0a1220',
            background: busy || !code.trim() ? '#64748b' : '#00f2ff',
            fontWeight: 700,
          }}
        >
          {busy ? 'PAIRING…' : 'PAIR'}
        </button>
      </div>
      {done && <div style={{ fontSize: 12, color: '#10b981' }}>Paired. Reloading…</div>}
      {error && <div style={{ fontSize: 12, color: '#ef4444' }}>{error}</div>}
    </form>
  );
}

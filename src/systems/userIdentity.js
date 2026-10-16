// src/systems/userIdentity.js
//
// Single source of truth for the *active user id*.
//
// Historically every frontend system hardcoded the literal 'user_default'
// (SessionTracker, PersonalitySystem, MemorySystem, GovernancePanel,
// AnalyticsDashboard…). That made multi-user support impossible and silently
// collapsed every install onto one tenant. This module replaces those literals.
//
// Design:
//   • The id is persisted to localStorage so a returning user keeps their
//     identity across reloads.
//   • When localStorage is unavailable (Node tests, private mode, blocked
//     storage) we fall back to an in-memory slot — the app still works, it
//     just doesn't persist across restarts.
//   • `FALLBACK_USER_ID` is kept ONLY for callers that explicitly need the
//     legacy value; normal code should use getUserId().
import { useSyncExternalStore } from 'react';

export const STORAGE_KEY = 'aariya.user_id';
export const FALLBACK_USER_ID = 'user_default';

// ── storage adapter ──────────────────────────────────────────────────────────

let memorySlot = null;

function safeStorage() {
  try {
    if (typeof localStorage !== 'undefined' && localStorage) return localStorage;
  } catch {
    /* storage can throw in private mode / sandboxed iframes */
  }
  return null;
}

function readStored() {
  const store = safeStorage();
  if (store) {
    try {
      return store.getItem(STORAGE_KEY);
    } catch {
      /* fall through to memory */
    }
  }
  return memorySlot;
}

function writeStored(value) {
  memorySlot = value;
  const store = safeStorage();
  if (store) {
    try {
      store.setItem(STORAGE_KEY, value);
    } catch {
      /* keep the in-memory copy regardless */
    }
  }
}

// ── id generation ────────────────────────────────────────────────────────────

/**
 * Generate a fresh, stable-looking user id. Prefers crypto.randomUUID (available
 * in every modern browser and Node 19+) and degrades to a timestamp+random id.
 */
export function generateUserId() {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return `user_${crypto.randomUUID()}`;
    }
  } catch {
    /* randomUUID can be unavailable in insecure contexts */
  }
  return `user_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
}

// ── public API ───────────────────────────────────────────────────────────────

let currentUserId = null;
const listeners = new Set();

function notify(next) {
  for (const fn of listeners) {
    try {
      fn(next);
    } catch {
      /* a bad subscriber must not break identity propagation */
    }
  }
}

/**
 * Return the active user id, creating and persisting one on first call.
 * Never returns '' — always a usable id.
 */
export function getUserId() {
  if (currentUserId) return currentUserId;

  const stored = readStored();
  if (typeof stored === 'string' && stored.trim()) {
    currentUserId = stored.trim();
  } else {
    currentUserId = generateUserId();
    writeStored(currentUserId);
  }
  return currentUserId;
}

/**
 * Explicitly set the active user id (e.g. after sign-in or account switch).
 * No-op when the value is unchanged.
 */
export function setUserId(id) {
  const next = id != null && String(id).trim() ? String(id).trim() : FALLBACK_USER_ID;
  if (next === currentUserId) return next;

  currentUserId = next;
  writeStored(next);
  notify(next);
  return next;
}

/** Subscribe to user-id changes. Returns an unsubscribe function. */
export function subscribeUserId(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** React hook: re-renders the caller when the active user id changes. */
export function useUserId() {
  return useSyncExternalStore(subscribeUserId, getUserId, getUserId);
}

/** Test helper — reset the module's cached id and subscribers. */
export function _resetUserIdentityForTests() {
  currentUserId = null;
  memorySlot = null;
  listeners.clear();
}

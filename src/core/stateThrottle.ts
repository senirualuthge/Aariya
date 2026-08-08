// src/core/stateThrottle.ts
import React from 'react';
/**
 * Zustand Write Throttling System
 * 
 * Prevents excessive React re-renders by batching state updates
 * Target: ≤10 store writes/sec
 */

interface PendingState {
  [key: string]: any;
}

class StateThrottle {
  private pendingState: PendingState = {};
  private commitScheduled: boolean = false;
  private commitInterval: number = 100; // 10 Hz
  private stateSetters: Set<(state: PendingState) => void> = new Set();

  constructor() {
    console.log('[State Throttle] Initialized (10 Hz commit rate)');
  }

  /**
   * Register a Zustand setState function
   */
  registerStore(setState: (state: PendingState) => void): void {
    this.stateSetters.add(setState);
  }

  /**
   * Unregister a store
   */
  unregisterStore(setState: (state: PendingState) => void): void {
    this.stateSetters.delete(setState);
  }

  /**
   * Queue a state update (will be committed in next batch)
   */
  queueUpdate(partial: PendingState): void {
    Object.assign(this.pendingState, partial);
    this.scheduleCommit();
  }

  /**
   * Schedule a commit if not already scheduled
   */
  private scheduleCommit(): void {
    if (this.commitScheduled) return;

    this.commitScheduled = true;
    setTimeout(() => {
      this.commit();
    }, this.commitInterval);
  }

  /**
   * Commit all pending state updates
   */
  private commit(): void {
    if (Object.keys(this.pendingState).length === 0) {
      this.commitScheduled = false;
      return;
    }

    // Apply to all registered stores
    for (const setState of this.stateSetters) {
      setState(this.pendingState);
    }

    this.pendingState = {};
    this.commitScheduled = false;
  }

  /**
   * Force immediate commit (bypass throttling)
   */
  forceCommit(): void {
    if (this.commitScheduled) {
      this.commit();
    }
  }

  /**
   * Set commit rate in Hz
   */
  setRate(hz: number): void {
    this.commitInterval = 1000 / hz;
    console.log(`[State Throttle] Rate set to ${hz} Hz`);
  }

  /**
   * Get current pending state
   */
  getPendingState(): PendingState {
    return { ...this.pendingState };
  }

  /**
   * Check if commit is scheduled
   */
  isCommitScheduled(): boolean {
    return this.commitScheduled;
  }
}

export const stateThrottle = new StateThrottle();

/**
 * Hook to use throttled state updates with Zustand
 * 
 * Usage:
 * ```ts
 * import { useThrottledStore } from './stateThrottle';
 * 
 * const useStore = create((set) => ({
 *   // ... your store
 * }));
 * 
 * // In component
 * const { queueUpdate } = useThrottledStore(useStore);
 * queueUpdate({ someKey: 'value' });
 * ```
 */
export function useThrottledStore(useStore: any) {
  // Register the store's setState on mount
  React.useEffect(() => {
    stateThrottle.registerStore(useStore.setState);
    return () => stateThrottle.unregisterStore(useStore.setState);
  }, [useStore]);

  return {
    queueUpdate: (partial: PendingState) => stateThrottle.queueUpdate(partial),
    forceCommit: () => stateThrottle.forceCommit(),
  };
}

// stateThrottle is already exported above as `export const stateThrottle`

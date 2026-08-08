import React, { useEffect, useRef } from 'react';
import useStore from '../store';
import { brainClient, BRAIN_THOUGHT_EVENT } from './brainClient';
import { eventBus } from '../core/EventBus';

/**
 * VoiceSystem — lives for the whole session.
 * Opens the cognitive-loop WebSocket and:
 *   - syncs brain state updates into the store
 *   - receives PROACTIVE messages from the 24/7 autonomy daemon
 *   - receives autonomy.inner_world / plan approval events
 *   - registers a sender so the UI can approve plans / toggle autonomy
 *
 * On mount it also hydrates Aariya's Mind panel from the REST state
 * endpoint so goals/plans from a previous session (e.g. a plan already
 * awaiting approval) are visible immediately instead of waiting for
 * the next daemon broadcast.
 */

// Normalize the daemon's inner-world payload into the shape the panel reads.
// The daemon sends snake_case (active_goal); the panel consumes activeGoal.
// Also derive the pending approval card from any awaiting_approval plan so
// an existing plan shows up even if its broadcast was missed.
function hydrateAutonomyState(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const goal = raw.active_goal || raw.activeGoal || null;
  const plans = raw.plans || [];
  const awaiting = plans.find((p) => p.status === 'awaiting_approval');
  let pendingPlan = raw.pendingPlan || null;
  if (awaiting && !pendingPlan) {
    pendingPlan = {
      plan_id: awaiting.id,
      goal: (goal && goal.description) || 'a goal',
      goal_type: goal ? goal.goal_type : null,
      risk_level: awaiting.risk_level || 'low',
      status: awaiting.status,
      steps: (awaiting.steps || []).map((s) => ({
        type: s.type,
        description: s.description || s.type,
        requires_approval: !!s.requires_approval,
      })),
    };
  }
  return {
    ...raw,
    activeGoal: goal,
    pendingPlan,
  };
}

function VoiceSystem() {
  const ws = useRef(null);
  const updateState = useStore(s => s.updateState);
  const setAutonomyState = useStore(s => s.setAutonomyState);
  const addProactiveMessage = useStore(s => s.addProactiveMessage);
  const addThought = useStore(s => s.addThought);
  const registerSender = useStore(s => s.registerSender);

  useEffect(() => {
    const host = window.location.hostname || 'localhost';

    // Visible inner life — Aariya's private thoughts (after replying) and idle
    // stream-of-consciousness musings flow into the chat as dimmed "thought"
    // lines, so you can watch her think even when she isn't speaking.
    const unsubThoughts = eventBus.subscribe(BRAIN_THOUGHT_EVENT, addThought);

    // Hydrate the Mind panel from persisted state on load (goals, plans,
    // awaiting-approval card, insight feed, audit trail).
    fetch(`http://${host}:8000/api/autonomy/state`)
      .then((r) => r.ok ? r.json() : null)
      .then((raw) => {
        if (raw) setAutonomyState(hydrateAutonomyState(raw));
      })
      .catch(() => {/* server may still be booting — broadcasts will fill in */});

    ws.current = new WebSocket(`ws://${host}:8000/ws/dashboard/stream`);

    ws.current.onopen = () => {
      registerSender((msg) => {
        if (ws.current?.readyState === WebSocket.OPEN) {
          ws.current.send(JSON.stringify(msg));
        }
      });
    };

    ws.current.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }

      // Let the brain client correlate chat requests → replies (text.stream /
      // ai_response) and surface her private thoughts to the inner-life feed.
      brainClient.handleServerMessage(data);

      switch (data.type) {
        case 'state.update':
          updateState(data.state);
          break;

        // Aariya reached out on her own — show it in the chat stream
        case 'proactive_message':
          addProactiveMessage(data.content, {
            trigger: data.trigger,
            timestamp: data.timestamp,
          });
          break;

        // Full inner-world snapshot (goals, plans, insights, audit)
        case 'autonomy.state':
          // hydrateAutonomyState derives the approval card from any
          // awaiting_approval plan and nulls it when none remains — so this
          // both fills the panel and drops stale cards.
          setAutonomyState(hydrateAutonomyState(data.state));
          break;

        // A plan needs user approval
        case 'plan.approval_requested':
          setAutonomyState({
            pendingPlan: data.plan,
            plans: [data.plan, ...(useStore.getState().autonomy.plans || [])],
          });
          break;

        // Approval outcome — clear the stale approval card once decided
        case 'plan.ack':
        case 'autonomy.ack':
          setAutonomyState({ lastAck: data, pendingPlan: null });
          break;

        default:
          break;
      }
    };

    return () => {
      registerSender(null);
      unsubThoughts();
      ws.current?.close();
    };
  }, [updateState, setAutonomyState, addProactiveMessage, addThought, registerSender]);

  return null;
}

export default VoiceSystem;

import React, { useEffect, useRef } from 'react';
import useStore from '../store';
import { brainClient, BRAIN_THOUGHT_EVENT } from './brainClient';
import { eventBus } from '../core/EventBus';
import { apiBase, apiWsBase } from '../utils/apiHost';

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
  const synWs = useRef(null);
  const updateState = useStore(s => s.updateState);
  const setAutonomyState = useStore(s => s.setAutonomyState);
  const addProactiveMessage = useStore(s => s.addProactiveMessage);
  const addThought = useStore(s => s.addThought);
  const registerSender = useStore(s => s.registerSender);
  const setSynoptic = useStore(s => s.setSynoptic);
  const pushAutonomyActivity = useStore(s => s.pushAutonomyActivity);
  const setLastProactive = useStore(s => s.setLastProactive);
  const setPlanStatus = useStore(s => s.setPlanStatus);

  useEffect(() => {
    // Visible inner life — Aariya's private thoughts (after replying) and idle
    // stream-of-consciousness musings flow into the chat as dimmed "thought"
    // lines, so you can watch her think even when she isn't speaking.
    const unsubThoughts = eventBus.subscribe(BRAIN_THOUGHT_EVENT, addThought);

    // Hydrate the Mind panel from persisted state on load (goals, plans,
    // awaiting-approval card, insight feed, audit trail). Also seed the live
    // strip's plan-status chip so it isn't empty on first paint.
    fetch(`${apiBase()}/api/autonomy/state`)
      .then((r) => r.ok ? r.json() : null)
      .then((raw) => {
        if (raw) {
          setAutonomyState(hydrateAutonomyState(raw));
          updatePlanStatusFromState(raw);
        }
      })
      .catch(() => {/* server may still be booting — broadcasts will fill in */});

    ws.current = new WebSocket(`${apiWsBase()}/ws/dashboard/stream`);

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

        // Aariya reached out on her own — show it in the chat stream + the
        // live strip (latest proactive action is surfaced in the Mind panel).
        case 'proactive_message':
          addProactiveMessage(data.content, {
            trigger: data.trigger,
            timestamp: data.timestamp,
          });
          setLastProactive({
            content: data.content,
            trigger: data.trigger,
            urgency: data.urgency,
            timestamp: data.timestamp,
          });
          pushAutonomyActivity({
            kind: 'proactive',
            title: data.trigger || 'proactive',
            text: data.content,
            severity: 'info',
            timestamp: data.timestamp,
            // The daemon logs the same action as a DAEMON log line whose text
            // is exactly "Proactive (<trigger>): <first 60 chars>", so the
            // strip entry can jump to its matching Event Log line.
            logMatch: {
              tag: 'DAEMON',
              text: `Proactive (${data.trigger}): ${String(data.content || '').slice(0, 60)}`,
            },
          });
          break;

        // Full inner-world snapshot (goals, plans, insights, audit)
        case 'autonomy.state':
          // hydrateAutonomyState derives the approval card from any
          // awaiting_approval plan and nulls it when none remains — so this
          // both fills the panel and drops stale cards.
          setAutonomyState(hydrateAutonomyState(data.state));
          // Plan status for the live strip: derive from the same snapshot.
          updatePlanStatusFromState(data.state);
          break;

        // A plan needs user approval
        case 'plan.approval_requested':
          setAutonomyState({
            pendingPlan: data.plan,
            plans: [data.plan, ...(useStore.getState().autonomy.plans || [])],
          });
          setPlanStatus({
            plan_id: data.plan?.plan_id,
            goal: data.plan?.goal,
            status: 'awaiting_approval',
            risk_level: data.plan?.risk_level,
          });
          pushAutonomyActivity({
            kind: 'plan',
            plan_id: data.plan?.plan_id,
            title: 'plan awaiting approval',
            text: data.plan?.goal || 'A plan needs your approval',
            severity: 'warn',
            timestamp: data.timestamp,
            // Matching PLANNER log line: "Plan awaits approval: <goal> (N steps)".
            logMatch: { tag: 'PLANNER', text: 'Plan awaits approval' },
          });
          break;

        // Approval outcome — clear the stale approval card once decided.
        // (plan.ack only: autonomy.ack is an enable-toggle reply, not a plan
        // lifecycle change, so it must never touch the plan chip.)
        case 'plan.ack': {
          // The server echoes plan_id in plan.ack; fall back to the last known
          // id (from the chip / pending card) so the status update always lands.
          const prev = useStore.getState().autonomy;
          const planId = data.plan_id
            || prev.planStatus?.plan_id
            || prev.pendingPlan?.plan_id
            || null;
          setAutonomyState({ lastAck: data, pendingPlan: null });
          if (planId) {
            const status = data.status || (data.ok ? 'running' : 'rejected');
            const goal = prev.planStatus?.goal || prev.pendingPlan?.goal;
            setPlanStatus({ plan_id: planId, goal, status });
            pushAutonomyActivity({
              kind: 'plan',
              plan_id: planId,
              title: `plan ${status}`,
              text: goal || planId,
              severity: data.ok ? 'info' : 'warn',
              timestamp: data.timestamp || Date.now() / 1000,
              // Matching PLANNER log lines from approve/reject.
              logMatch: { tag: 'PLANNER', text: data.ok ? 'Plan approved' : 'Plan rejected' },
            });
          }
          break;
        }

        // Enable/disable reply — just record it, never touch plan state.
        case 'autonomy.ack':
          setAutonomyState({ lastAck: data });
          break;

        // Idle inner life — also surfaces in the live strip so the panel
        // stays alive between real daemon actions.
        case 'stream_of_consciousness':
          pushAutonomyActivity({
            kind: 'thought',
            title: 'stream of consciousness',
            text: data.thought,
            severity: 'info',
            timestamp: data.timestamp,
            // Matching DAEMON log line: "Stream of consciousness: <first 60 chars>".
            logMatch: {
              tag: 'DAEMON',
              text: `Stream of consciousness: ${String(data.thought || '').slice(0, 60)}`,
            },
          });
          break;

        // LSTM self-retrain completed — model status change.
        case 'autonomy.model_trained':
          pushAutonomyActivity({
            kind: 'model',
            title: 'emotion model retrained',
            text: data.reason || 'Predictor retrained',
            severity: 'info',
            timestamp: data.timestamp,
            // Matching MODEL log line: "Emotion predictor retrained (...)".
            logMatch: { tag: 'MODEL', text: 'Emotion predictor retrained' },
          });
          break;

        default:
          break;
      }
    };

    // Helper: keep the live strip's plan-status chip in sync with the daemon's
    // inner-world snapshot (the authoritative plan state). Clears the chip when
    // no plans remain so a stale "AWAITING APPROVAL" never lingers.
    function updatePlanStatusFromState(state) {
      if (!state || typeof state !== 'object') return;
      const plans = state.plans || [];
      const awaiting = plans.find((p) => p.status === 'awaiting_approval');
      const running = plans.find((p) => p.status === 'running');
      const latest = plans[0];
      const goal = (state.active_goal || {}).description || 'a goal';
      if (awaiting) {
        setPlanStatus({
          plan_id: awaiting.id,
          goal,
          status: 'awaiting_approval',
          risk_level: awaiting.risk_level,
        });
      } else if (running) {
        setPlanStatus({
          plan_id: running.id,
          goal,
          status: 'running',
          risk_level: running.risk_level,
        });
      } else if (latest) {
        setPlanStatus({
          plan_id: latest.id,
          goal,
          status: latest.status,
        });
      } else {
        setPlanStatus(null);
      }
    }

    // Dedicated high-frequency synoptics frame stream (Agents Swarm Visualize
    // §238). The dashboard stream carries `state.update` with the full synoptic
    // dict; this second channel feeds the predictive ghost/orbit overlays the
    // per-frame `state[] / prediction / anomalies / features` contract without
    // waiting for a full brain round-trip.
    synWs.current = new WebSocket(`${apiWsBase()}/ws/synoptics`);
    synWs.current.onopen = () => {
      synWs.current.send(JSON.stringify({ subscribe: true }));
    };
    synWs.current.onmessage = (event) => {
      let frame;
      try {
        frame = JSON.parse(event.data);
      } catch {
        return;
      }
      if (frame?.type !== 'synoptics_update') return;
      setSynoptic((prev) => ({
        ...prev,
        ...(frame.state ? { domains: frame.state.reduce((acc, p) => {
          acc[p.id] = (p.x ?? 0) / 100;
          return acc;
        }, {}) } : {}),
        predicted: frame.prediction?.reduce((acc, p) => {
          acc[p.id] = p.x / 100;
          return acc;
        }, {}) ?? prev?.predicted,
        anomalies: frame.anomalies ?? prev?.anomalies ?? [],
        cognition: frame.cognition ?? prev?.cognition,
        causal: frame.causal ?? prev?.causal,
        desktop: frame.desktop ?? prev?.desktop,
        user_model: frame.user_model ?? prev?.user_model,
        goal: frame.goal ?? prev?.goal,
        plan: frame.plan ?? prev?.plan,
        hierarchical_goals: frame.hierarchical_goals ?? prev?.hierarchical_goals ?? [],
        hierarchical_plan: frame.hierarchical_plan ?? prev?.hierarchical_plan,
        arcs: frame.arcs ?? prev?.arcs ?? [],
        task_plan: frame.task_plan ?? prev?.task_plan,
        executor: frame.executor ?? prev?.executor,
        last_plan_action: frame.last_plan_action ?? prev?.last_plan_action,
        swarm_stability: frame.swarm_stability ?? prev?.swarm_stability,
        narrative_drift: frame.narrative_drift ?? prev?.narrative_drift,
        intent: frame.intent ?? prev?.intent,
        gnn: frame.gnn ?? prev?.gnn,
        prediction_g: frame.prediction_g ?? prev?.prediction_g,
        causal_learned: frame.causal_learned ?? prev?.causal_learned,
        strategic: frame.strategic ?? prev?.strategic,
        trend_meta: frame.trend_meta ?? prev?.trend_meta,
        // Prediction / policy / proactive frame keys (NEWPredictionPRT2 §6/§11,
        // Agents Swarm Visualize): merged verbatim so BrainScene can render the
        // selected reply action, RL style, social-action constraints, proactive
        // alerts, belief state, and per-frame swarm features (density/entropy).
        selected_action: frame.selected_action ?? prev?.selected_action,
        rl_style: frame.rl_style ?? prev?.rl_style,
        social_action: frame.social_action ?? prev?.social_action,
        proactive_alerts: frame.proactive_alerts ?? prev?.proactive_alerts,
        belief_state: frame.belief_state ?? prev?.belief_state,
        society: frame.society ?? prev?.society,
        features: frame.features ?? prev?.features,
        swarm_features: {
          density: frame.features?.density ?? prev?.features?.density ?? 0,
          entropy: frame.features?.entropy ?? prev?.features?.entropy ?? 0,
          avg_velocity: frame.features?.avg_velocity ?? prev?.features?.avg_velocity ?? 0,
        },
        swarm_meta: {
          model_version: frame.meta?.model_version ?? prev?.meta?.model_version,
          latency_ms: frame.meta?.latency_ms ?? prev?.meta?.latency_ms,
        },
        // Merge the frame timestamp into the synoptic dict so the BrainScene
        // timeline scrubber (which keys on synoptic.timestamp) can capture
        // and replay historical frames.
        timestamp: frame.timestamp ?? prev?.timestamp,
        synoptic_frame_ts: frame.timestamp,
      }));
    };
    synWs.current.onerror = () => {
      // Optional overlay stream — fail silently; state.update still covers it.
      synWs.current?.close();
    };

    return () => {
      registerSender(null);
      unsubThoughts();
      synWs.current?.close();
      ws.current?.close();
      ws.current?.close();
    };
  }, [updateState, setAutonomyState, addProactiveMessage, addThought, registerSender,
      pushAutonomyActivity, setLastProactive, setPlanStatus]);

  return null;
}

export default VoiceSystem;

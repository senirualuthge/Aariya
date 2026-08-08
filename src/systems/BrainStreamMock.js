import { useState, useEffect, useRef } from 'react';
import useStore from '../store';
import { useAgentRegistry } from '../hooks/useAgentRegistry';

// Module-level registry: nodeId → timestamp (ms) when the agent first
// exceeded the activation threshold. Persists across React re-mounts.
const AGENT_ACTIVE_SINCE = {};
const ACTIVATION_THRESHOLD = 0.1;

/** Record the first-active timestamp for a node, if not already set. */
function markActiveIfNew(nodeId, activation) {
    if (activation >= ACTIVATION_THRESHOLD && !AGENT_ACTIVE_SINCE[nodeId]) {
        AGENT_ACTIVE_SINCE[nodeId] = Date.now();
    }
}

function hashCode(str) {
    let hash = 0;
    for (let i = 0; i < str.length; i++) hash = str.charCodeAt(i) + ((hash << 5) - hash);
    return Math.abs(hash);
}
function generateColor(name) {
    const hue = hashCode(name) % 360;
    return `hsl(${hue}, 80%, 65%)`;
}

/**
 * A mock hook to simulate the real-time AI Brain state stream.
 * In production (Phase 3), this will be replaced with an actual WebSocket
 * connection to the Kafka stream from the Python backend.
 */
export function useBrainStream() {
    const { agents } = useAgentRegistry();
    const agentsRef = useRef(agents);

    // Keep ref updated to avoid stale closures in setInterval
    useEffect(() => {
        agentsRef.current = agents;
    }, [agents]);

    const [brainData, setBrainData] = useState({
        trust: 0.5,
        valence: 0.5,
        arousal: 0.5,
        nodes: [
            { id: 'emotion', category: 'emotion', label: 'Emotion Agent', position: [-2, 0, 0], activation: 0 },
            { id: 'memory', category: 'memory', label: 'Memory Agent', position: [0, 1.5, -1], activation: 0 },
            { id: 'reasoning', category: 'reasoning', label: 'Reasoning Agent', position: [2, 0, 0], activation: 0 },
            { id: 'personality', category: 'personality', label: 'Personality Agent', position: [0, -1.5, 0], activation: 0 },
            { id: 'critic', category: 'critic', label: 'Critic Agent', position: [0, 0, 2], activation: 0 },
        ],
        edges: [
            { id: 'e-m', from: 'emotion', to: 'memory', active: false },
            { id: 'e-r', from: 'emotion', to: 'reasoning', active: false },
            { id: 'm-r', from: 'memory', to: 'reasoning', active: false },
            { id: 'p-r', from: 'personality', to: 'reasoning', active: false },
            { id: 'r-c', from: 'reasoning', to: 'critic', active: false }
        ],
        system: {
            tokenSpeed: 82,
            wsLatency: 14,
            gpuUsage: 45,
            queueLag: 5,
            timeline: []
        },
        user: {
            engagementTime: '0m 0s',
            engagementSeconds: 0,
            dropOffPoints: 0,
            emotionalImprovement: 0
        }
    });

    useEffect(() => {
        // Connect to real-time WebSocket Stream for Brain
        const wsUrl = `ws://${window.location.hostname}:8000/ws/brain_metrics`;
        let ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log("Connected to neural metrics stream");
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                // Signals are handled by useSignalStream in AnalyticsDashboard (always-on).
                // Session updates are likewise handled there to avoid double-processing.

                if (data.type === "neural_update") {
                    setBrainData(prev => ({
                        ...prev,
                        trust: data.trust ?? prev.trust,
                        valence: data.valence ?? prev.valence,
                        arousal: data.arousal ?? prev.arousal,
                        nodes: prev.nodes.map(node => {
                            if (data.agent_activations && data.agent_activations[node.id] !== undefined) {
                                const act = data.agent_activations[node.id];
                                markActiveIfNew(node.id, act);
                                return {
                                    ...node,
                                    activation: act,
                                    activeSince: AGENT_ACTIVE_SINCE[node.id] ?? null,
                                };
                            }
                            return node;
                        }),
                        edges: prev.edges.map(edge => {
                            const actFrom = data.agent_activations?.[edge.from] || 0;
                            const actTo = data.agent_activations?.[edge.to] || 0;
                            return { ...edge, active: (actFrom > 0.4 || actTo > 0.4) };
                        })
                    }));
                }
            } catch(e) {
                console.error("Error parsing neural update:", e);
            }
        };

        // Fallback smoothing/decay if no messages arrive recently
        // NOW HOOKED INTO REAL USER/AI STATE (Auto-Adaptation)
        const interval = setInterval(() => {
            const state = useStore.getState();
            const { userEmotion, emotions, speaking, thinking, userSpeaking, trust } = state;
            const liveAgents = agentsRef.current || [];

            // Define targeted agent activations based on live system intents
            const emotionAct = Math.max(0, ...Object.values(emotions || {}));
            const reasoningAct = thinking ? 0.9 : 0.15;
            const personalityAct = speaking ? 0.8 : 0.2;
            const criticAct = (userEmotion?.valence < -0.2) ? 0.8 : 0.1;
            const memoryAct = userSpeaking ? 0.7 : 0.15;

            const lerp = (start, end, amt) => (1 - amt) * start + amt * end;

            setBrainData(prev => {
                const newGpu = Math.min(100, Math.max(0, prev.system.gpuUsage + (Math.random() * 6 - 3)));
                const newLatency = Math.min(200, Math.max(5, prev.system.wsLatency + (Math.random() * 10 - 5)));
                const newSeconds = prev.user.engagementSeconds + 0.3; // 300ms
                const mins = Math.floor(newSeconds / 60);
                const secs = Math.floor(newSeconds % 60);
                
                const timeline = [...prev.system.timeline, {
                    time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
                    gpu: newGpu,
                    latency: newLatency
                }].slice(-20); // keep last 20 frames

                let newNodes = [...prev.nodes];
                let newEdges = [...prev.edges];
                const existingNodeIds = new Set(newNodes.map(n => n.id));

                // Add newly discovered agents
                liveAgents.forEach((agent, i) => {
                    if (agent.status === "removed") return;
                    
                    const agentId = `dyn-${agent.id}`;
                    if (!existingNodeIds.has(agentId)) {
                        // Use a golden angle spiral to perfectly distribute an infinite number of agents without overlapping
                        const goldenRatio = (1 + Math.sqrt(5)) / 2;
                        const angle = i * Math.PI * 2 * goldenRatio;
                        const radius = 5.5 + (i * 0.45); // Spirals infinitely outward
                        const yPosition = Math.sin(i * 1.7) * 3.5; // Waves up and down to use 3D space
                        const position = [
                            Math.cos(angle) * radius, 
                            yPosition, 
                            Math.sin(angle) * radius
                        ];
                        
                        newNodes.push({
                            id: agentId,
                            category: 'discovery',
                            label: agent.display_name || agent.name || 'Discovered Agent',
                            position,
                            activation: 0,
                            isDynamic: true,
                            color: generateColor(agent.name || agentId)
                        });
                        
                        // Connect dynamic agents to reasoning module
                        newEdges.push({
                            id: `e-${agentId}-r`,
                            from: agentId,
                            to: 'reasoning',
                            active: false,
                            isDynamic: true
                        });

                        // Daisy-chain connection between adjacent dynamic agents
                        if (i > 0) {
                            const prevAgentId = `dyn-${liveAgents[i-1].id}`;
                            newEdges.push({
                                id: `e-${prevAgentId}-${agentId}`,
                                from: prevAgentId,
                                to: agentId,
                                active: false,
                                isDynamic: true
                            });
                        }
                        
                        existingNodeIds.add(agentId);
                    }
                });

                // Remove agents that are no longer active
                const currentAgentIds = new Set(liveAgents.filter(a => a.status !== 'removed').map(a => `dyn-${a.id}`));
                newNodes = newNodes.filter(n => !n.isDynamic || currentAgentIds.has(n.id));
                newEdges = newEdges.filter(e => !e.isDynamic || currentAgentIds.has(e.from));

                // Map target activations and stamp activeSince on first-active
                const nextNodes = newNodes.map(n => {
                    let target = 0;
                    if (n.id === 'emotion') target = emotionAct;
                    else if (n.id === 'reasoning') target = reasoningAct;
                    else if (n.id === 'personality') target = personalityAct;
                    else if (n.id === 'critic') target = criticAct;
                    else if (n.id === 'memory') target = memoryAct;
                    else if (n.isDynamic) target = Math.random() > 0.7 ? Math.random() * 0.8 : 0.1;

                    // Add small noise to make it feel alive
                    const newActivation = lerp(n.activation, target, 0.3) + (Math.random() * 0.08);
                    markActiveIfNew(n.id, newActivation);

                    return {
                        ...n,
                        activation: newActivation,
                        activeSince: AGENT_ACTIVE_SINCE[n.id] ?? null,
                    };
                });

                // Activate edges if connected nodes are highly active
                const nextEdges = newEdges.map(e => {
                    const fromAct = nextNodes.find(n => n.id === e.from)?.activation || 0;
                    const toAct = nextNodes.find(n => n.id === e.to)?.activation || 0;
                    return { ...e, active: (fromAct > 0.45 && toAct > 0.45) };
                });

                // Safe defaults for valence/arousal
                const safeValence = userEmotion?.valence !== undefined && !isNaN(userEmotion.valence) ? (userEmotion.valence + 1) / 2 : 0.5;
                const safeArousal = userEmotion?.arousal !== undefined && !isNaN(userEmotion.arousal) ? userEmotion.arousal : 0.5;

                return {
                    ...prev,
                    trust: lerp(prev.trust, trust || 0.5, 0.1),
                    valence: lerp(prev.valence, safeValence, 0.15),
                    arousal: lerp(prev.arousal, safeArousal, 0.15),
                    nodes: nextNodes,
                    edges: nextEdges,
                    system: {
                        ...prev.system,
                        gpuUsage: Math.round(newGpu),
                        wsLatency: Math.round(newLatency),
                        tokenSpeed: Math.round(prev.system.tokenSpeed + (Math.random() * 2 - 1)),
                        timeline
                    },
                    user: {
                        ...prev.user,
                        engagementSeconds: newSeconds,
                        engagementTime: `${mins}m ${secs}s`,
                        emotionalImprovement: Math.round((prev.valence - 0.5) * 100)
                    }
                };
            });
        }, 300);

        return () => {
            ws.close();
            clearInterval(interval);
        };
    }, []);

    return brainData;
}

// systems/DialogueSystem.jsx - AI-Powered Version
import { useEffect, useCallback, useRef } from 'react';
import useStore from '../store';
import { useSpeechRecognition } from '../hooks/useSpeechRecognition';
import { useAudioAnalyzer } from '../hooks/useAudioAnalyzer'; 
import { enhancedSpeak } from './voicePresets';
import { handleMessage, analyzeUserEmotion } from './aiEngine';
import { getFlirtMode } from './safety/flirtController';
import { detectStress } from './safety/stressDetector'; 
import { detectFatigue, shortenResponse } from './safety/fatigueDetector';
import { resolveIntimacy } from './safety/intimacyController';
import { updateEmotions, calculateEmotionTargets } from './emotionEngine'; 
import { eventBus } from '../core/EventBus';
import { neuralEngine } from './ai/NeuralEngine'; // NEW
import { personalitySystem } from './ai/PersonalitySystem'; // NEW
import { analytics } from './analytics/AnalyticsSystem'; // NEW
import { detectSleepTime, getCircadianPhase, getSilentResponse } from './voice/voiceIntelligence';
import { detectUserMood, applyPersonalityNudge } from './userMoodDetector';

export default function DialogueSystem() {
    useAudioAnalyzer(); // Activate Microphone Analysis
    const {
        listening,
        transcript
    } = useSpeechRecognition();

    const {
        manualInput,
        setSpeaking, // Kept from original
        addLog,
        voicePitch,
        voiceRate,
        setThinking, // Kept from original
        conversationContext = { userName: 'Player', lastInteraction: null, relationshipLevel: 0 },
        currentPersonality,
        setEmotionIntensity,
        setUserMood,
        setAiMood,
        setPersonality,
        setPersonalityPreset,
        increaseRelationship,
        setMessages
    } = useStore();



    // The original code had useSpeechRecognition() here.
    // The new structure implies destructuring from useSpeechRecognition() at the top.
    // So, this line is redundant if the destructuring is used.
    // useSpeechRecognition(); // Removed as per new structure implied by instruction's snippet

    // Updated params ref to include isStressed, isFatigued, accent, isNightMode, etc.
    // ...

    // --- ANALYTICS SESSION LIFECYCLE ---
    useEffect(() => {
        analytics.startSession();
        return () => {
            analytics.endSession(true); // Natural end if unmounted gracefully
        };
    }, []);

    // --- MAIN DIALOGUE LOOP ---
    const conversationHistoryRef = useRef([]); // To keep track of full context for API
    const silentModeCounter = useRef(0);
    const params = useRef({ 
        mode: currentPersonality, 
        isStressed: false, 
        isFatigued: false, 
        accent: 'neutral',
        isNightMode: false,
        isAccessibility: false, 
        userVoiceStats: null,
        circadianPhase: 'day', 
        isSilentMode: false 
    }); 

    // Sync ref mode with store's currentPersonality
    useEffect(() => {
        params.current.mode = currentPersonality;
    }, [currentPersonality]);

    // --- EVENT BUS SUBSCRIPTIONS ---
    useEffect(() => {
        const unsubscribe = eventBus.subscribe('emotion:changed', (emotions) => {
            // We can react to smooth emotion changes without store selectors
            // For example, finding the strongest emotion
            const strongest = Object.entries(emotions).reduce((a, b) => a[1] > b[1] ? a : b);
            if (strongest[1] > 0.8 && strongest[0] !== 'calm') {
                console.log(`[DialogueSystem] Strong emotion detected: ${strongest[0]}`);
            }
        });
        return unsubscribe;
    }, []);

    // --- BARGE-IN IMPLEMENTATION ---
    useEffect(() => {
        if (listening) {
            // User started speaking -> Hard Stop TTS
            if (window.speechSynthesis.speaking) {
                window.speechSynthesis.cancel();
                setSpeaking(false);
                addLog('system', 'TTS Interrupted (Barge-in)');
            }
        }
    }, [listening, addLog, setSpeaking]); // Added setSpeaking to dependencies

    const speak = useCallback((text, overrideMode = null) => {
        const mode = overrideMode || params.current.mode;
        // Check safety/context for whisper
        const isWhisperAllowed = (mode === 'flirty' || mode === 'cutie' || mode === 'calm');
        
        enhancedSpeak(
            text, 
            setSpeaking, 
            addLog, 
            voicePitch, 
            voiceRate, 
            mode, 
            params.current.isStressed, 
            isWhisperAllowed,
            params.current.isFatigued,
            params.current.accent,
            params.current.isNightMode,
            params.current.isAccessibility,
            params.current.userVoiceStats,
            params.current.circadianPhase,
            params.current.isSilentMode
        );

    }, [setSpeaking, addLog, voicePitch, voiceRate]);

    const markHabitDone = async (habitName) => {
        try {
            await fetch(`http://localhost:5000/api/done/${habitName}`, { method: 'POST' });
            console.log("Habit marked as done:", habitName);
        } catch (error) {
            console.error("Failed to mark habit done:", error);
        }
    };

    // --- MUSIC CONTROLLER (Existing) ---
    const audioRef = useRef(null);
    useEffect(() => {
        const checkMusic = () => {
            if (!audioRef.current) return;
            const audio = audioRef.current;
            audio.volume = 0.08; 
            const isMusicMood = (params.current.isNightMode || params.current.mode === 'calm' || params.current.isStressed);
            if (isMusicMood) { /*...*/ } else { audio.pause(); }
        };
        const interval = setInterval(checkMusic, 2000); 
        return () => clearInterval(interval);
    }, []);

    // --- EMOTION HEARTBEAT (Neural Engine / Logic Layer) ---
    // Updates emotions continuously based on decay and environmental inputs
    // (read.txt: "Emotion parameters feed AnimBP variables... Decay rule: Very Important")
    useEffect(() => {
        let currentTargets = { ...useStore.getState().emotions };
        let lastTime = Date.now();
        let activeSilenceDuration = 0;

        const heartbeat = setInterval(() => {
            const now = Date.now();
            const dt = (now - lastTime) / 1000;
            lastTime = now;

            const state = useStore.getState();
            const { 
                userAudioStats = { energy: 0, highFreqRatio: 0, isLoud: false }, 
                emotions, 
                userSpeaking, 
                userMood, 
                userEmotion = { primary: 'neutral', arousal: 0.0, valence: 0.0 }
            } = state; // userMood is roughly Valence from text

            // Update Silence Timer
            if (!userSpeaking) {
                activeSilenceDuration += dt;
            } else {
                activeSilenceDuration = 0;
            }

            // 1. CONSTRUCT NEURAL INPUT VECTOR
            // We map available signals to the Neural Engine's expected format [-1, 1]
            // 1. CONSTRUCT NEURAL INPUT VECTOR (TRIPLE-SIGNAL FUSION)
            // Text valence from lexical detection
            let textValence = 0.0;
            if (userMood === 'happy' || userMood === 'excited' || userMood === 'grateful') textValence = 0.8;
            if (userMood === 'sad' || userMood === 'angry' || userMood === 'anxious') textValence = -0.7;
            
            // Fused userEmotion contains integrated Face + Audio states
            const faceAudioValence = userEmotion?.valence || 0;
            const faceAudioArousal = userEmotion?.arousal || 0;
            
            // Blend them (prioritize text slightly if it expresses strong emotion, else rely on face/audio)
            const finalValence = textValence !== 0 ? (textValence * 0.6 + faceAudioValence * 0.4) : faceAudioValence;
            const finalArousal = faceAudioArousal > 0 ? faceAudioArousal : ((userAudioStats?.energy || 0) / 100);

            const inputs = {
                valence: finalValence, 
                arousal: finalArousal,
                engagement: userSpeaking || (userEmotion?.arousal > 0.5) ? 1.0 : 0.0,
                speechDensity: 0.5, // Placeholder
                silence: Math.min(activeSilenceDuration / 10, 1.0)
            };

            // 2. RUN NEURAL ENGINE (Shadow Mode)
            const neuralResult = neuralEngine.update(inputs);

            // 3. APPLY OUTPUTS
            if (neuralResult) {
                // The Neural Engine updates the PersonalitySystem internally.
                // We read the 'Behavior Modifiers' to drive our Animation Layer.
                // const mods = personalitySystem.getBehaviorModifiers();
                
                // Drive Emotion Intensities based on Personality Axes
                // E.g. High Energy -> Higher 'Happy' or 'Surprised' limits
                // High Warmth -> Higher 'Calm' baseline
                
                // We still use our Physics/Decay engine for the raw values, 
                // but we Bias the targets using the neural output.
                
                // Calc base environmental targets (Audio/Silence rules)
                 const envTargets = calculateEmotionTargets(
                    currentTargets, 
                    userAudioStats || { energy: 0, isLoud: false }, 
                    activeSilenceDuration, 
                    personalitySystem?.currentTemplate?.name || 'Calm'
                );
                
                // Blend Neural Bias
                // If Neural says "Increase Warmth", we boost 'calm' and 'happy'
                if (neuralResult.delta.warmth > 0) {
                     envTargets.calm = Math.min(envTargets.calm + 0.1, 1.0);
                }
                
                // 4. DECAY & STORE UPDATE
                const nextEmotions = updateEmotions(emotions, envTargets, dt);
                
                // Sync detailed logs if debugging
                if (neuralResult.safetyTriggered) {
                     console.log("[Neural] Safety Guard Triggered: De-escalating.");
                }

                // Sync Axes to UI Store (Visualization)
                useStore.getState().setPersonalityAxes(neuralResult.currentAxes);

                let changed = false;
                for (let key in nextEmotions) {
                    if (Math.abs(nextEmotions[key] - emotions[key]) > 0.01) {
                        changed = true;
                        break;
                    }
                }
                if (changed) useStore.getState().setAllEmotions(nextEmotions);
            }

        }, 100); // 10Hz

        return () => clearInterval(heartbeat);
    }, []);



    const processInput = useCallback(async (input) => {
        if (!input) return;

        console.log("Processing:", input);
        setThinking(true);

        // Let the 24/7 autonomy daemon know the user is active (the chat is
        // local, so without this the daemon would assume endless silence)
        useStore.getState().notifyUserActivity();

        // 1. Analyse user emotion and update state
        const emotionAnalysis = await analyzeUserEmotion(input);

        // ── MOOD DETECTION: drive AI personality from user's words ──────────
        const moodResult = detectUserMood(input);
        if (moodResult.confidence > 0) {
            // Store the detected user mood
            setUserMood(moodResult.userMood);
            setAiMood(moodResult.aiMood);

            // Nudge personality axes (warmth/energy/assertiveness/formality)
            const currentP = useStore.getState().personality;
            const updatedP = applyPersonalityNudge(currentP, moodResult.personalityDelta);
            setPersonality(updatedP);

            // Sync personalityPreset so the voice layer picks the right style (if auto is enabled)
            if (useStore.getState().autoPersonality) {
                setPersonalityPreset(moodResult.aiMood);
            }

            // Push emotion targets directly into the emotion engine
            const targets = moodResult.emotionTargets;
            Object.entries(targets).forEach(([em, val]) => {
                setEmotionIntensity(em, val);
            });

            console.log(`[Mood] user=${moodResult.userMood} → ai=${moodResult.aiMood} (conf=${moodResult.confidence.toFixed(2)})`);
        } else if (emotionAnalysis.detected) {
            // Fall back to legacy analyzeUserEmotion result
            const { userAudioStats } = useStore.getState();
            const baseIntensity = userAudioStats.isLoud ? 1.0 : 0.5;
            setUserMood(emotionAnalysis.emotion);
            setEmotionIntensity(emotionAnalysis.emotion, baseIntensity);
        }

        try {
            // 0. Detect Stress, Fatigue, Sleep (Immediate reaction)
            const isStressed = detectStress(input);
            const isFatigued = detectFatigue(input);
            const currentHour = new Date().getHours();
            const isNightMode = detectSleepTime(input, currentHour);
            const circadianPhase = getCircadianPhase(currentHour);

            // Silent Mode Trigger
            if (input.toLowerCase().includes("just listen") || input.toLowerCase().includes("stay quiet")) {
                params.current.isSilentMode = true;
                silentModeCounter.current = 0;
            } else if (input.toLowerCase().includes("help") || input.includes("?")) {
                params.current.isSilentMode = false;
            }
            
            params.current.isStressed = isStressed;
            params.current.isFatigued = isFatigued;
            params.current.isNightMode = isNightMode;
            params.current.circadianPhase = circadianPhase;

            // Handle Silent Mode Logic
            if (params.current.isSilentMode) {
                silentModeCounter.current += 1;
                const silentResp = getSilentResponse(null, silentModeCounter.current);
                // ... (rest of silent logic)
                if (silentResp) {
                     setThinking(false);
                     speak(silentResp);
                     setMessages(prev => [...prev, { role: 'user', text: input }, { role: 'bot', text: silentResp }]);
                     return;
                } else {
                     setThinking(false);
                     setMessages(prev => [...prev, { role: 'user', text: input }]);
                     return;
                }
            }

            // --- AUTO GOOD NIGHT RESPONSE ---
            let autoResponse = null;
            if (isNightMode && input.toLowerCase().includes("good night")) {
                autoResponse = "It sounds like it’s time to rest… Sleep well!";
                // We skip LLM processing to avoid high energy or lengthy goodbyes
                setThinking(false);
                setMessages(prev => [...prev, { role: 'user', text: input }, { role: 'bot', text: autoResponse }]);
                speak(autoResponse);
                return;
            }

            // Call new Modular Architecture
            // We pass unmodified input to LLM mostly, but could modify context if needed.
            // Using handleMessage as is.
            //
            // Stream the reply live into a chat bubble so she "speaks" as the
            // brain generates tokens (backend path). A ref tracks the bubble.
            let botMsgIndex = useStore.getState().chatHistory.length;
            setMessages(prev => {
                botMsgIndex = prev.length;
                return [...prev, { role: 'bot', text: '', streaming: true }];
            });

            const { text, memory } = await handleMessage("default_user", input, {
                onChunk: (streamed) => {
                    setMessages(prev => {
                        const copy = [...prev];
                        if (copy[botMsgIndex]) copy[botMsgIndex] = { ...copy[botMsgIndex], text: streamed };
                        return copy;
                    });
                },
            });

            // Sync Store & Calculate State
            let targetPersonality = currentPersonality;
            
            if (memory) {
                 if (memory.profile?.name && memory.profile.name !== conversationContext.userName) {
                     useStore.getState().setUserName(memory.profile.name);
                 }
                 
                 // Intimacy & Flirt Control
                 // 1. Get user setting (default 1)
                 const userIntimacy = memory.profile?.intimacyLevel ?? 1;
                 // 2. Resolve usable level (safety clamped)
                 resolveIntimacy(userIntimacy, memory);
                 
                 // 3. Get Flirt Mode (requires passing allowedIntimacy? or relying on getFlirtMode's internal logic?)
                 // getFlirtMode currently relies on Risk + Mood.
                 // We should ideally update getFlirtMode to respect the allowedIntimacy cap.
                 // For now, we trust getFlirtMode's risk check, but we should probably inform it.
                 // Let's rely on getFlirtMode for now as it handles safety risk primarily.
                 let currentVoiceMode = getFlirtMode(memory);
                 
                 params.current.accent = memory.profile?.accent || 'neutral';
                 params.current.mode = currentVoiceMode;
            }

            let response = text;
            
            // Post-Process: Shorten if Fatigued
            if (isFatigued) {
                response = shortenResponse(response);
            }

            // 4. (Optional) Legacy Habit Parsing
            const habitDoneMatch = response.match(/\[DONE:([^\]]+)\]/i);
            if (habitDoneMatch) {
                markHabitDone(habitDoneMatch[1].trim());
            }

            // Clean response for display/speech
            const cleanResponse = response
                .replace(/\[DONE:[^\]]+\]/gi, '')
                .trim();

            // 5. Update relationship level for positive interaction
            increaseRelationship(1);

            // Update conversation history
            conversationHistoryRef.current.push(
                { role: 'user', content: input },
                { role: 'assistant', content: cleanResponse }
            );

            // Keep history manageable (last 10 exchanges)
            if (conversationHistoryRef.current.length > 20) {
                conversationHistoryRef.current = conversationHistoryRef.current.slice(-20);
            }

            // Finalize the streamed bubble (or append if no chunks arrived)
            setMessages(prev => {
                const copy = [...prev];
                if (copy[botMsgIndex]) {
                    copy[botMsgIndex] = { ...copy[botMsgIndex], text: cleanResponse, streaming: false };
                } else {
                    copy.push({ role: 'bot', text: cleanResponse });
                }
                return copy;
            });

            // Visible inner life — her private thought right after replying
            const thought = memory?.thought;
            if (thought) {
                setMessages(prev => [...prev, { role: 'thought', text: thought }]);
            }

            setThinking(false);
            speak(cleanResponse, targetPersonality);

        } catch (error) {
            console.error("AI Error:", error);
            setThinking(false);

            const fallback = "*giggles nervously* Sorry sweetie, I got a bit distracted! Can you say that again? 💕";
            speak(fallback);
        }

    }, [speak, setThinking, conversationContext, setUserMood, increaseRelationship, currentPersonality, setEmotionIntensity, setMessages, setAiMood, setPersonality, setPersonalityPreset]);

    const { clearInputs } = useStore();

    // Effect for Voice Input
    useEffect(() => {
        if (transcript) {
            addLog('user', transcript);
            processInput(transcript);
            clearInputs();
        }
    }, [transcript, addLog, processInput, clearInputs]);

    // Effect for Manual Text Input
    useEffect(() => {
        if (manualInput) {
            addLog('user', manualInput);
            processInput(manualInput);
            clearInputs();
        }
    }, [manualInput, addLog, processInput, clearInputs]);

    // Load voices
    useEffect(() => {
        if (typeof window !== 'undefined' && window.speechSynthesis) {
            window.speechSynthesis.onvoiceschanged = () => {
                console.log("Voices loaded");
            };
        }
    }, []);

    return null;
}

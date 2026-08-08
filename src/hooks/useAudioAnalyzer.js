import { useEffect, useRef } from 'react';
import useStore from '../store';

/**
 * useAudioAnalyzer.js
 * Analyzes microphone input for volume and energy dynamics.
 * Updates store.userVolume and store.userAudioStats.
 */
export function useAudioAnalyzer() {
    const { started, setUserVolume, setUserAudioStats, setUserSpeaking } = useStore();
    const audioContextRef = useRef(null);
    const analyserRef = useRef(null);
    const dataArrayRef = useRef(null);
    const sourceRef = useRef(null);
    const rafIdRef = useRef(null);
    const streamRef = useRef(null);

    useEffect(() => {
        if (!started) return;

        const initAudio = async () => {
            try {
                // Check if context exists or create new
                if (!audioContextRef.current) {
                    audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();
                }
                
                // Resume if suspended
                if (audioContextRef.current.state === 'suspended') {
                    await audioContextRef.current.resume();
                }

                streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
                
                const audioCtx = audioContextRef.current;
                analyserRef.current = audioCtx.createAnalyser();
                analyserRef.current.fftSize = 256;
                
                sourceRef.current = audioCtx.createMediaStreamSource(streamRef.current);
                sourceRef.current.connect(analyserRef.current);
                
                const bufferLength = analyserRef.current.frequencyBinCount;
                dataArrayRef.current = new Uint8Array(bufferLength);

                const analyze = () => {
                    analyserRef.current.getByteFrequencyData(dataArrayRef.current);

                    // Calculate Average Volume (RMS-ish)
                    let sum = 0;
                    for (let i = 0; i < bufferLength; i++) {
                        sum += dataArrayRef.current[i];
                    }
                    const average = sum / bufferLength;
                    
                    // Normalize to 0-100 range roughly
                    // Usually byte data is 0-255. 0-50 is quiet, 50-100 is conversational, 150+ is loud.
                    // We map 0-255 -> 0-100 for easier store usage, or keep 0-255.
                    
                    const volume = average; // 0-255
                    
                    // Energy Analysis (High vs Low Freq)
                    // Lower half = Bass/Vowels, Upper half = Treble/Consonants
                    const split = Math.floor(bufferLength / 2);
                    let lowSum = 0;
                    let highSum = 0;
                    
                    for (let i = 0; i < split; i++) lowSum += dataArrayRef.current[i];
                    for (let i = split; i < bufferLength; i++) highSum += dataArrayRef.current[i];
                    
                    const lowAvg = lowSum / split;
                    const highAvg = highSum / (bufferLength - split);
                    
                    const highFreqRatio = highAvg / (lowAvg + 1); // Avoid div/0
                    const isLoud = volume > 40; // Threshold for "Loud"
                    const isSpeaking = volume > 10; // Threshold for "Voice Activity"

                    // Update Store safely (throttle if needed, but rAF is usually fine for UI updates like visuals)
                    // We might want to throttle store updates to 30fps or 10fps if performance drops.
                    // For now, raw update.
                    setUserVolume(volume);
                    setUserSpeaking(isSpeaking); // Real VAD
                    setUserAudioStats({
                         energy: volume,
                         highFreqRatio: highFreqRatio,
                         isLoud: isLoud
                    });

                    rafIdRef.current = requestAnimationFrame(analyze);
                };

                analyze();

            } catch (err) {
                console.error("Microphone access denied or error:", err);
            }
        };

        initAudio();

        return () => {
            if (rafIdRef.current) cancelAnimationFrame(rafIdRef.current);
            if (streamRef.current) {
                streamRef.current.getTracks().forEach(track => track.stop());
            }
            if (audioContextRef.current) audioContextRef.current.close();
            audioContextRef.current = null;
        };
    }, [started, setUserVolume, setUserAudioStats, setUserSpeaking]);

    return null; // Logic only hook
}

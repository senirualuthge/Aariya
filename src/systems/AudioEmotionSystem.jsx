import { useEffect, useRef } from 'react';
import useStore from '../store';
import { runtime } from './RuntimeLoop';

export default function AudioEmotionSystem() {
    const { setAudioEmotion } = useStore();
    const audioContextRef = useRef(null);
    const analyserRef = useRef(null);
    const dataArrayRef = useRef(null);

    useEffect(() => {
        // Get microphone access (same as camera, already requested)
        navigator.mediaDevices.getUserMedia({ audio: true, video: false })
            .then(stream => {
                // Create audio context
                const audioContext = new (window.AudioContext || window.webkitAudioContext)();
                const analyser = audioContext.createAnalyser();
                analyser.fftSize = 2048;
                
                const source = audioContext.createMediaStreamSource(stream);
                source.connect(analyser);
                
                audioContextRef.current = audioContext;
                analyserRef.current = analyser;
                dataArrayRef.current = new Uint8Array(analyser.frequencyBinCount);

                console.log('🎤 Audio Emotion System initialized');
            })
            .catch(err => {
                console.warn('Audio access denied:', err);
                // Set neutral emotion
                setAudioEmotion({ valence: 0, arousal: 0, confidence: 0 });
            });

        return () => {
            if (audioContextRef.current) {
                audioContextRef.current.close();
            }
        };
    }, [setAudioEmotion]);

    useEffect(() => {
        const update = () => {
             if (!analyserRef.current || !dataArrayRef.current) return;

             analyserRef.current.getByteFrequencyData(dataArrayRef.current);
             
             // Extract features
             const { energy, pitch, tempo } = extractAudioFeatures(dataArrayRef.current);
             
             // Map to emotion
             const { valence, arousal, confidence } = audioToEmotion(energy, pitch, tempo);
             
             setAudioEmotion({ valence, arousal, confidence });
        };

        // Subscribe with priority 0 (Sensors)
        const unsubscribe = runtime.subscribe(update, 0, 'AudioEmotionSystem');

        return () => {
            unsubscribe();
        };
    }, [setAudioEmotion]);

    return null; // Logic-only
}

// Extract audio features
function extractAudioFeatures(dataArray) {
    // Energy (overall loudness)
    const energy = dataArray.reduce((sum, val) => sum + val, 0) / dataArray.length / 255;
    
    // Pitch (weighted by low vs high frequency)
    const lowFreq = dataArray.slice(0, 50).reduce((sum, val) => sum + val, 0);
    const highFreq = dataArray.slice(50, 200).reduce((sum, val) => sum + val, 0);
    const pitch = (highFreq - lowFreq) / (highFreq + lowFreq + 1);
    
    // Tempo (variance in energy over time - simplified)
    const variance = dataArray.reduce((sum, val, i, arr) => {
        if (i === 0) return 0;
        return sum + Math.abs(val - arr[i-1]);
    }, 0) / dataArray.length;
    const tempo = Math.min(variance / 50, 1.0);
    
    return { energy, pitch, tempo };
}

// Map audio features to emotion (valence/arousal)
function audioToEmotion(energy, pitch, tempo) {
    // Valence: pitch + energy
    // High pitch + high energy = happy
    // Low pitch + low energy = sad
    const valence = (pitch * 0.6) + (energy * 0.4) - 0.3;
    
    // Arousal: energy + tempo
    // High energy + high tempo = excited
    // Low energy + low tempo = calm
    const arousal = (energy * 0.7) + (tempo * 0.3);
    
    // Confidence: higher when audio is present
    const confidence = Math.min(energy * 1.5, 1.0);
    
    return {
        valence: Math.max(-1, Math.min(1, valence)),
        arousal: Math.max(0, Math.min(1, arousal)),
        confidence: Math.max(0, Math.min(1, confidence))
    };
}

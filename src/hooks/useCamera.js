import { useEffect, useRef } from 'react';
import useStore from '../store';

export function useCamera() {
    const videoRef = useRef(null);
    const audioContextRef = useRef(null);
    const analyzerRef = useRef(null);
    const { started, setTracking, setUserVolume, setUserSpeaking, setVideoRef } = useStore();

    useEffect(() => {
        if (!started) return;

        setVideoRef(videoRef);

        let stream = null;
        let animationFrame = null;

        const setupCamera = async () => {
            try {
                stream = await navigator.mediaDevices.getUserMedia({
                    video: { width: 640, height: 480, facingMode: 'user' },
                    audio: true // Enable audio for reactivity
                });

                if (videoRef.current) {
                    videoRef.current.srcObject = stream;
                    videoRef.current.onloadedmetadata = () => {
                        videoRef.current.play();
                        setTracking(true);
                    };
                }

                let analyzer = null;
                
                // Setup Audio Analyzer
                try {
                    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
                    if (AudioContextClass) {
                        const audioContext = new AudioContextClass();
                        const source = audioContext.createMediaStreamSource(stream);
                        analyzer = audioContext.createAnalyser();
                        analyzer.fftSize = 256;
                        source.connect(analyzer);
                        
                        audioContextRef.current = audioContext;
                        analyzerRef.current = analyzer;
                    }
                } catch (e) {
                    console.warn("AudioContext processing failed (ignoring):", e);
                }

                if (analyzer) {
                    const bufferLength = analyzer.frequencyBinCount;
                    const dataArray = new Uint8Array(bufferLength);
                    
                    const updateVolume = () => {
                        if (!analyzerRef.current) return;
                        
                        analyzer.getByteFrequencyData(dataArray);
                        
                        // 1. Calculate Energy (RMS)
                        let sum = 0;
                        for (let i = 0; i < bufferLength; i++) {
                            sum += dataArray[i];
                        }
                        const average = sum / bufferLength;
                        const normalizedEnergy = average / 128.0; 

                        // 2. Calculate High Frequency Ratio (Pitch Proxy)
                        // Split spectrum: Low (0 - half), High (half - end)
                        const splitIndex = Math.floor(bufferLength / 2);
                        let lowSum = 0, highSum = 0;
                        
                        for(let i = 0; i < splitIndex; i++) lowSum += dataArray[i];
                        for(let i = splitIndex; i < bufferLength; i++) highSum += dataArray[i];

                        const lowAvg = lowSum / splitIndex;
                        const highAvg = highSum / (bufferLength - splitIndex);
                        
                        // Ratio: > 1 means more high freq (excited/question), < 1 means low freq (calm/serious)
                        // Safety check for divide by zero
                        const highFreqRatio = lowAvg > 0 ? (highAvg / lowAvg) : 0; 
                        
                        // 3. Update Store
                        setUserVolume(normalizedEnergy);
                        setUserSpeaking(normalizedEnergy > 0.05); // Threshold
                        
                        const { setUserAudioStats } = useStore.getState();
                        setUserAudioStats({
                            energy: normalizedEnergy,
                            highFreqRatio: highFreqRatio,
                            isLoud: normalizedEnergy > 0.6 // Flag for "Loud"
                        });

                        animationFrame = requestAnimationFrame(updateVolume);
                    };
                    updateVolume();
                }

            } catch (err) {
                console.error("Media access denied:", err);
            }
        };

        setupCamera();

        return () => {
            if (stream) {
                stream.getTracks().forEach(track => track.stop());
            }
            if (audioContextRef.current) {
                audioContextRef.current.close();
            }
            if (animationFrame) {
                cancelAnimationFrame(animationFrame);
            }
            setTracking(false);
            setUserVolume(0);
            setUserSpeaking(false);
            setVideoRef(null);
        };
    }, [started, setTracking, setUserVolume, setUserSpeaking, setVideoRef]);

    return videoRef;
}

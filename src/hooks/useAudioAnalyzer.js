import { useEffect, useRef } from 'react';
import useStore from '../store';

/**
 * useAudioAnalyzer.js
 * Analyzes microphone input for volume and energy dynamics.
 * Updates store.userVolume and store.userAudioStats.
 *
 * Track B: additionally captures a REAL 16 kHz / 16-bit mono PCM snapshot of
 * the most recent speech window and publishes it on userAudioStats as
 * `pcm16b64` (+ `pcmSampleRate`). brainClient forwards it with the chat turn so
 * the backend can run webrtcvad + speaker diarization. The visual analysis
 * (volume/energy) is unchanged — a second analyser node taps the same stream.
 */

const TARGET_SAMPLE_RATE = 16000;
const PCM_WINDOW_SECONDS = 0.6;    // audio window sent per turn
const PCM_KEEP_SECONDS = 1.5;      // rolling capture buffer
const PCM_ENCODE_INTERVAL_MS = 200;

/** Linear-interpolation resample — a real (if simple) resampler. */
function resampleLinear(input, srcRate, dstRate) {
    if (srcRate === dstRate || input.length === 0) return input;
    const nDst = Math.max(1, Math.round((input.length * dstRate) / srcRate));
    const out = new Float32Array(nDst);
    const step = srcRate / dstRate;
    for (let i = 0; i < nDst; i++) {
        const pos = i * step;
        const lo = Math.floor(pos);
        const hi = Math.min(lo + 1, input.length - 1);
        const frac = pos - lo;
        out[i] = input[lo] * (1 - frac) + input[hi] * frac;
    }
    return out;
}

function floatToInt16(input) {
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i++) {
        const v = Math.max(-1, Math.min(1, input[i]));
        out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
    }
    return out;
}

function int16ToBase64(int16) {
    const bytes = new Uint8Array(int16.buffer, int16.byteOffset, int16.byteLength);
    let binary = '';
    const CHUNK = 0x8000;
    for (let i = 0; i < bytes.length; i += CHUNK) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
    }
    return btoa(binary);
}

export function useAudioAnalyzer() {
    const { started, setUserVolume, setUserAudioStats, setUserSpeaking } = useStore();
    const audioContextRef = useRef(null);
    const analyserRef = useRef(null);
    const dataArrayRef = useRef(null);
    const sourceRef = useRef(null);
    const rafIdRef = useRef(null);
    const streamRef = useRef(null);

    // Track B: PCM tap
    const pcmAnalyserRef = useRef(null);
    const pcmBufferRef = useRef(null);
    const pcmChunksRef = useRef([]);
    const pcmLengthRef = useRef(0);
    const lastEncodeRef = useRef(0);
    const pcmInfoRef = useRef({ pcm16b64: null, pcmSampleRate: TARGET_SAMPLE_RATE });

    useEffect(() => {
        if (!started) return;

        const initAudio = async () => {
            try {
                if (!audioContextRef.current) {
                    audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)();
                }

                if (audioContextRef.current.state === 'suspended') {
                    await audioContextRef.current.resume();
                }

                streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });

                const audioCtx = audioContextRef.current;
                analyserRef.current = audioCtx.createAnalyser();
                analyserRef.current.fftSize = 256;

                sourceRef.current = audioCtx.createMediaStreamSource(streamRef.current);
                sourceRef.current.connect(analyserRef.current);

                // Second tap for real time-domain PCM (does not change visuals).
                pcmAnalyserRef.current = audioCtx.createAnalyser();
                pcmAnalyserRef.current.fftSize = 2048;
                pcmBufferRef.current = new Float32Array(pcmAnalyserRef.current.fftSize);
                sourceRef.current.connect(pcmAnalyserRef.current);

                const bufferLength = analyserRef.current.frequencyBinCount;
                dataArrayRef.current = new Uint8Array(bufferLength);

                const analyze = () => {
                    analyserRef.current.getByteFrequencyData(dataArrayRef.current);

                    let sum = 0;
                    for (let i = 0; i < bufferLength; i++) {
                        sum += dataArrayRef.current[i];
                    }
                    const average = sum / bufferLength;
                    const volume = average; // 0-255

                    const split = Math.floor(bufferLength / 2);
                    let lowSum = 0;
                    let highSum = 0;
                    for (let i = 0; i < split; i++) lowSum += dataArrayRef.current[i];
                    for (let i = split; i < bufferLength; i++) highSum += dataArrayRef.current[i];

                    const lowAvg = lowSum / split;
                    const highAvg = highSum / (bufferLength - split);
                    const highFreqRatio = highAvg / (lowAvg + 1);
                    const isLoud = volume > 40;
                    const isSpeaking = volume > 10;

                    // ── Real PCM capture (Track B) ────────────────────────────
                    if (pcmAnalyserRef.current && pcmBufferRef.current) {
                        pcmAnalyserRef.current.getFloatTimeDomainData(pcmBufferRef.current);
                        pcmChunksRef.current.push(pcmBufferRef.current.slice());
                        pcmLengthRef.current += pcmBufferRef.current.length;

                        const maxSamples = audioCtx.sampleRate * PCM_KEEP_SECONDS;
                        while (
                            pcmLengthRef.current > maxSamples &&
                            pcmChunksRef.current.length > 1
                        ) {
                            pcmLengthRef.current -= pcmChunksRef.current.shift().length;
                        }

                        const now = performance.now();
                        if (now - lastEncodeRef.current > PCM_ENCODE_INTERVAL_MS) {
                            lastEncodeRef.current = now;
                            const want = Math.floor(audioCtx.sampleRate * PCM_WINDOW_SECONDS);
                            const parts = [];
                            let total = 0;
                            for (let i = pcmChunksRef.current.length - 1; i >= 0 && total < want; i--) {
                                parts.unshift(pcmChunksRef.current[i]);
                                total += pcmChunksRef.current[i].length;
                            }
                            if (total > 0) {
                                const merged = new Float32Array(total);
                                let off = 0;
                                for (const p of parts) {
                                    merged.set(p, off);
                                    off += p.length;
                                }
                                const tail = merged.subarray(Math.max(0, merged.length - want));
                                const resampled = resampleLinear(
                                    tail, audioCtx.sampleRate, TARGET_SAMPLE_RATE
                                );
                                pcmInfoRef.current = {
                                    pcm16b64: int16ToBase64(floatToInt16(resampled)),
                                    pcmSampleRate: TARGET_SAMPLE_RATE,
                                };
                            }
                        }
                    }

                    setUserVolume(volume);
                    setUserSpeaking(isSpeaking);
                    setUserAudioStats({
                        energy: volume,
                        highFreqRatio: highFreqRatio,
                        isLoud: isLoud,
                        ...pcmInfoRef.current,
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
            pcmAnalyserRef.current = null;
            pcmChunksRef.current = [];
            pcmLengthRef.current = 0;
            pcmInfoRef.current = { pcm16b64: null, pcmSampleRate: TARGET_SAMPLE_RATE };
        };
    }, [started, setUserVolume, setUserAudioStats, setUserSpeaking]);

    return null; // Logic only hook
}

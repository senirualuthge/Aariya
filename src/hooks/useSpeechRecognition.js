import { useEffect } from 'react';
import useStore from '../store';

export function useSpeechRecognition() {
    const { started, setListening, setTranscript, listening, transcript } = useStore();

    useEffect(() => {
        if (!started) return;

        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

        if (!SpeechRecognition) {
            console.warn("Speech Recognition API not supported in this browser.");
            return;
        }

        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';

        recognition.onstart = () => setListening(true);
        recognition.onend = () => setListening(false);

        recognition.onresult = (event) => {
            const current = event.resultIndex;
            const transcript = event.results[current][0].transcript;
            if (event.results[current].isFinal) {
                setTranscript(transcript);
                console.log("Heard:", transcript);
            }
        };

        recognition.start();

        return () => {
            recognition.stop();
        };
    }, [started, setListening, setTranscript]);

    return {
        listening,
        transcript,
        startListening: () => {}, // Placeholders to match DialogueSystem expectations
        stopListening: () => {},
        resetTranscript: () => setTranscript(''),
        browserSupportsSpeechRecognition: !!(window.SpeechRecognition || window.webkitSpeechRecognition)
    };
}

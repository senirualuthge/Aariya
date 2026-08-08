// VisionSystem.jsx - Facial presence detection + user emotion heuristics.
// (Avatar head-tracking removed.)

import { useEffect, useRef } from 'react';
import * as tf from '@tensorflow/tfjs';
import * as faceDetection from '@tensorflow-models/face-detection';
import { useCamera } from '../hooks/useCamera';
import useStore from '../store';

// Initialize backend efficiently
tf.ready().then(() => {
    console.log("TensorFlow ready");
});

export default function VisionSystem() {
    const videoRef = useCamera();
    const detectorRef = useRef(null);
    const loopRef = useRef(null);

    useEffect(() => {
        const loadModel = async () => {
            const model = faceDetection.SupportedModels.MediaPipeFaceDetector;
            const detectorConfig = {
                runtime: 'tfjs',
                maxFaces: 1
            };
            try {
                detectorRef.current = await faceDetection.createDetector(model, detectorConfig);
                console.log("Face Detector loaded");
            } catch (e) {
                console.error("Failed to load face detector", e);
            }
        };
        loadModel();

        return () => {
            if (loopRef.current) cancelAnimationFrame(loopRef.current);
        };
    }, []);

    useEffect(() => {
        const detect = async () => {
            if (detectorRef.current && videoRef.current && videoRef.current.readyState === 4) {
                try {
                    const faces = await detectorRef.current.estimateFaces(videoRef.current);
                    if (faces.length > 0) {
                        // Update face detection state
                        const { faceDetected, setFaceDetected } = useStore.getState();
                        
                        if (!faceDetected) {
                            setFaceDetected(true);
                            useStore.getState().setFaceLastSeen(Date.now());
                        }
                    } else {
                        // No faces detected
                        const { faceDetected, setFaceDetected, setUserEmotion } = useStore.getState();
                        if (faceDetected) {
                            setFaceDetected(false);
                            useStore.getState().setFaceLastSeen(Date.now());
                            setUserEmotion({ primary: 'bored', arousal: 0, valence: -0.1 });
                        }
                    }
                } catch (err) {
                    console.warn("Vision detect frame skipped:", err.message);
                }
            }
            loopRef.current = requestAnimationFrame(detect);
        };

        if (videoRef.current) {
            detect();
        }
    }, [videoRef]);

    // Hidden video element for processing
    return (
        <video
            ref={videoRef}
            style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '320px',
                height: '240px',
                opacity: 0.1, // Visible for debug, can hide later
                pointerEvents: 'none',
                zIndex: 100
            }}
            playsInline
            muted
            autoPlay
        />
    );
}

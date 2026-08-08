import { useEffect } from 'react';
import useStore from '../store';
import { updateEmotions } from './emotionEngine';
import { eventBus } from '../core/EventBus';
import { runtime } from './RuntimeLoop';

export default function EmotionSystem() {
    const { setAllEmotions } = useStore();

    useEffect(() => {
        const update = (deltaTime) => {
            // Get current state from store (direct access to avoid closure staleness)
            const state = useStore.getState();
            const { emotions, emotionTargets } = state;
            
            // Integrate Temporal Smoothing logic here
            // If emotionTargets are set (by sensors), we move towards them.
            // If not, updateEmotions handles natural decay.
            
            const targets = emotionTargets || {};

            const updated = updateEmotions(emotions, targets, deltaTime); 
            
            setAllEmotions(updated);

            // Publish update for other systems (Architecture Guide)
            eventBus.publish('emotion:changed', updated);
        };

        // Subscribe with priority 10 (after sensors, before personality/social)
        const unsubscribe = runtime.subscribe(update, 10, 'EmotionSystem');

        return () => {
            unsubscribe();
        };
    }, [setAllEmotions]);

    return null;
}

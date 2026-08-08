import { useEffect } from 'react';
import useStore from '../store';
import { runtime } from './RuntimeLoop';
import { neuralEngine } from './ai/NeuralEngine';

const SocialIntentSystem = () => {
    const setSocialIntent = useStore((state) => state.setSocialIntent);
    // We access state via getState() inside the loop to avoid re-renders

    useEffect(() => {
        const updateSocialIntent = (dt) => {
            const state = useStore.getState();
            
            // Delegate logic to Neural Engine
            const newIntent = neuralEngine.resolveSocialIntent(state, dt);
            
            setSocialIntent(newIntent);
        };

        // Subscribe with priority 30 (after emotions, before behavior)
        const unsubscribe = runtime.subscribe(updateSocialIntent, 30, 'SocialIntentSystem');

        return () => {
            unsubscribe();
        };
    }, [setSocialIntent]);

    return null;
};

export default SocialIntentSystem;

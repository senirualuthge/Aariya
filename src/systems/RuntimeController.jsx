import { useEffect } from 'react';
import { runtime } from './RuntimeLoop';
import useStore from '../store';

const RuntimeController = () => {
    const started = useStore((state) => state.started);

    useEffect(() => {
        if (started) {
            runtime.start();
        } else {
            runtime.stop();
        }

        return () => {
            runtime.stop();
        };
    }, [started]);

    return null; // Logic only, no UI
};

export default RuntimeController;

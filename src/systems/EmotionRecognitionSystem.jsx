// Simplified facial emotion tracking system
import React, { useEffect } from 'react';
import useStore from '../store';

function EmotionSystem() {
  const setUserEmotion = useStore(s => s.setUserEmotion);

  useEffect(() => {
    // Poll camera or listen to faceWorker
  }, []);

  return null;
}

export default EmotionSystem;
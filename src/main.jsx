import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';
import { initPrivacySwitches } from './utils/privacySwitches';

// Installed before the first render so the getUserMedia interceptor is in
// place for every capture request the app makes, and the server's mic/camera
// kill-switch state is loaded once at boot.
initPrivacySwitches();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
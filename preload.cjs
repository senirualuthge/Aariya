const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    getHabitStats: () => ipcRenderer.invoke('get-habit-stats'),
    getBuildSummary: () => ipcRenderer.invoke('get-build-summary'),
    openAnalytics: () => ipcRenderer.send('open-analytics'),
    // Panel persistence - uses main-process fs for crash-safe storage
    savePanelState: (state) => ipcRenderer.invoke('save-panel-state', state),
    loadPanelState: () => ipcRenderer.invoke('load-panel-state')
});

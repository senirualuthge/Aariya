# Camera Not Working - Debug Guide

## Quick Checks

### 1. **Browser Permissions**
The most common issue is browser camera permissions:

**Steps to fix:**
1. Look for a camera icon in your browser's address bar (🎥 or similar)
2. Click it and ensure permissions are set to "Allow"
3. Refresh the page
4. Click "Initialize System" button again

**Chrome/Edge:**
- Go to Settings → Privacy and Security → Site Settings → Camera
- Make sure `http://localhost:5173` is allowed

**Firefox:**
- Click the lock icon → Connection Details → Permissions
- Change Camera to "Allow"

### 2. **Camera Already in Use**
If another application is using your camera:
- Close all other apps that might use the camera (Zoom, Teams, Skype, etc.)
- Refresh the browser

### 3. **Check Browser Console**
Open Developer Tools (F12) and look for errors:
- Press F12
- Go to Console tab
- Look for errors mentioning `getUserMedia`, `NotAllowedError`, or `NotFoundError`

## Common Error Messages & Solutions

| Error | Meaning | Solution |
|-------|---------|----------|
| `NotAllowedError` | Permission denied | Allow camera in browser settings |
| `NotFoundError` | No camera detected | Check if camera is connected/enabled |
| `NotReadableError` | Camera in use | Close other apps using camera |
| `OverconstrainedError` | Requested settings not supported | Camera doesn't support 640x480 |

## Manual Test

Open your browser console (F12) and run:
```javascript
navigator.mediaDevices.getUserMedia({ video: true, audio: true })
  .then(stream => {
    console.log("✅ Camera access granted!", stream);
    stream.getTracks().forEach(track => track.stop());
  })
  .catch(err => {
    console.error("❌ Camera error:", err.name, err.message);
  });
```

## System Requirements

- Working webcam (built-in or USB)
- Microphone access
- Running on `http://localhost:5173` (or HTTPS in production)
- Modern browser (Chrome 90+, Edge 90+, Firefox 88+)

## Code Flow

1. Click "Initialize System" → `setStarted(true)`
2. `useCamera` hook activates
3. Requests camera permissions: `navigator.mediaDevices.getUserMedia()`
4. If granted → camera stream starts
5. Face detection systems begin working
6. "User Detected ✨" appears in status panel

## Still Not Working?

1. Try a different browser
2. Restart your computer
3. Check Windows Camera Privacy Settings:
   - Settings → Privacy → Camera
   - Make sure "Allow apps to access your camera" is ON
   - Make sure browser has permission

4. Test your camera in Windows Camera app to verify it works

## Developer Notes

The camera is initialized in: `src/hooks/useCamera.js`
- Line 18-21: Requesting camera with 640x480 resolution
- Both VisionSystem and EmotionRecognitionSystem use this hook
- Systems only activate when `started === true`

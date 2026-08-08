---
description: How to run the AI Companion application
---

# Running the AI Companion

// turbo-all

1. Install the dependencies:

```powershell
npm install
```

2. Create a `.env` file in the root directory with your Anthropic API key:

```env
VITE_ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

3. Start the development server:

```powershell
npm run dev
```

4. Open the application in your browser at `http://localhost:5173`.
5. Grant camera and microphone permissions when prompted for the vision and voice systems to work.

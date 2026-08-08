# Analysis of Voice & Avatar Architectures

## Executive Summary

You provided `voice TTS.txt`, `Avatarplan.txt`, and `AI Girl 2.txt` for analysis.
These documents represent the **"Body" and "Voice"** implementation details, whereas the previous `fixes.txt` represented the **"Brain" and "Nervous System"**.

**Key Conclusion:**
These files confirm that we need a **Layered Animation System**. They strongly advocate for game-engine-like architectures (State Machines, Blend Trees) which we must adapt for your React/Three.js tech stack.

---

## Detailed Breakdown

### 1. `voice TTS.txt` (The Voice)

**Status: Ready for Integration**
This file describes a sophisticated TTS engine that doesn't just "speak" but "performs".

- **Key Insight:** **Pre-Speech Anticipation**. The avatar must inhale (breath animation) ~200ms _before_ audio starts.
- **Integration Point:** This logic belongs in the **Social Intent System**. When the intent changes to `SPEAKING`, a "pre-speech" state is triggered before the actual TTS API is called.
- **Action:** Implement a `TTSManager` class that handles the `Text -> Emotion Parse -> Pre-Speech Delay -> Audio` pipeline.

### 2. `Avatarplan.txt` (The Body - Strategic)

**Status: Adapt Logic, Ignore "Unity" Specifics**
This file is a high-level guide to creating digital humans.

- **Conflict:** It heavily recommends Unity/Unreal Engine. Your project is currently **React + Three.js**.
- **Resolution:** We **stick with Three.js** but adapt the _concepts_:
  - **Unity "Animator Controller"** -> **Three.js `AnimationMixer` wrapper**.
  - **Unity "Blend Trees"** -> **Weighted Action Blending** in Three.js.
  - **State Machine** -> A custom JavaScript `AnimationStateManager`.
- **Critical Takeaway:** Do not animate manually. Use "Procedural Overlays" (e.g., generic "Idle" animation + "Nervous" shake applied on top).

### 3. `AI Girl 2.txt` (The Body - Tactical)

**Status: The "How-To" Manual**
This is the most practical file. It gives specific implementation details for the animation system.

- **The "Dead Mannequin" Fix:** It lists 5 mandatory channels to keep the avatar alive:
  1.  **Face:** 8-12 Blendshapes (Smile, Blink, Jaw, etc.).
  2.  **Lip Sync:** Viseme mapping (A, E, O, M, etc.).
  3.  **Micro-Motion:** Eyes and head must never be perfectly still.
  4.  **Breathing:** Continuous sine-wave animation on the chest bone.
  5.  **State Machine:** Explicit states (`Idle`, `Listening`, `Talking`).

---

## Integration with Unified Runtime Loop

Here is how these new files fit into the **Phase 1 (Runtime Loop)** plan:

| Architecture Layer     | Source File      | Implementation in Three.js                                           |
| :--------------------- | :--------------- | :------------------------------------------------------------------- |
| **Layer 0: Runtime**   | `fixes.txt`      | **`RuntimeLoop.js`** (The Heartbeat)                                 |
| **Layer 1: Intent**    | `fixes.txt`      | **`SocialIntentSystem.js`** (Decides _what_ to do)                   |
| **Layer 2: Voice**     | `voice TTS.txt`  | **`TTSService.js`** (Parses text, triggers pre-speech)               |
| **Layer 3: Behavior**  | `AI Girl 2.txt`  | **`AnimationController.js`** (State Machine: Idle -> Listen -> Talk) |
| **Layer 4: Rendering** | `Avatarplan.txt` | **`Avatar.jsx`** (Three.js mesh, Blendshapes, Visemes)               |

## Updated Roadmap Recommendation

We should keep the previous roadmap but flesh out the "Behavior" phase with these new details.

1.  **Phase 1: The Heartbeat** (Unified Runtime Loop) - _No Change, still priority #1_
2.  **Phase 2: The Social Brain** (Social Intent) - _No Change_
3.  **Phase 3: The Body (NEW)**
    - Implement the **State Machine** from `AI Girl 2.txt`.
    - Create the **Blendshape Manager** for facial expressions.
    - Implement **Viseme-based Lip Sync**.
4.  **Phase 4: The Voice (NEW)**
    - Implement the **Pre-Speech** logic from `voice TTS.txt`.

**Decision Needed:**
The plans heavily reference 3D assets (FBX files, Blendshapes).
**Do you have a GLB/FBX model ready with these blendshapes (JawOpen, Smile, Blink), or do we need to work with placeholder boxes/models for now?**

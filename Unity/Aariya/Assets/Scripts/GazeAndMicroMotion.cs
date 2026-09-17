using UnityEngine;
using Newtonsoft.Json.Linq;

// Gaze + micro head movement + Smile controller (*AI Girl 2* §"AVATAR RENDERER").
//
// Consumes the server's REAL `avatar.update` motion frames (emitted by the
// brain's cognitive loop after every turn and by the autonomy daemon while
// idle — never synthetic) and drives the AnimBP parameters the doc specifies:
//   HeadTilt (deg, ±5), EyeFocus (0-1), Posture (0-1), BlinkRate (0-1),
//   MicroMovement (0-1), Smile (0-1).
//
// All values are lerped so motion reacts to state changes only — no idle
// loops, no random gestures (doc: "minimal movement"). In STEALTH the
// movement scale drops so she is a quiet, still presence (MicroMovement ≈ 0).
//
// Optional: assign `smileRenderer` + `smileBlendShapeIndex` to apply Smile
// directly to a blendshape (mirrors BlinkController's pattern).
public class GazeAndMicroMotion : MonoBehaviour
{
    [Header("Animator")]
    public Animator avatarAnimator;

    [Header("Smile blendshape (optional)")]
    public SkinnedMeshRenderer smileRenderer;
    public int smileBlendShapeIndex = 1;  // ARKit jawOpen/smile slot per avatar

    [Header("Motion")]
    [Range(0.0f, 1.0f)]
    public float motionIntensity = 1.0f;  // master: 0 = full STEALTH stillness
    public float lerpSpeed = 4.0f;

    // Target values from the last real avatar.update frame.
    private float targetHeadTilt   = -5f;   // degrees (±5)
    private float targetEyeFocus   = 0.5f;
    private float targetPosture    = 0.7f;
    private float targetBlinkRate  = 1.0f;
    private float targetMicroMove  = 0.0f;
    private float targetSmile      = 0.0f;
    private string currentMode     = "CALM";

    // Smoothed current values.
    private float headTilt, eyeFocus, posture, blinkRate, microMove, smile;

    // Procedural gaze drift: only when EyeFocus is low (unfocused) does she
    // wander slightly; focused gaze stays locked (reaction-driven, bounded).
    private float gazeDrift = 0f;

    void OnEnable()
    {
        AIStateReceiver.OnAvatarFrame += HandleAvatarFrame;
    }

    void OnDisable()
    {
        AIStateReceiver.OnAvatarFrame -= HandleAvatarFrame;
    }

    void HandleAvatarFrame(JObject root)
    {
        JToken av = root["avatar"];
        if (av == null) return;

        targetHeadTilt  = av["HeadTilt"]?.Value<float>()  ?? targetHeadTilt;
        targetEyeFocus  = av["EyeFocus"]?.Value<float>()  ?? targetEyeFocus;
        targetPosture   = av["Posture"]?.Value<float>()   ?? targetPosture;
        targetBlinkRate = av["BlinkRate"]?.Value<float>() ?? targetBlinkRate;
        targetMicroMove = av["MicroMovement"]?.Value<float>() ?? targetMicroMove;
        targetSmile     = av["Smile"]?.Value<float>()     ?? targetSmile;
        currentMode     = root["mode"]?.Value<string>()   ?? currentMode;
    }

    void Update()
    {
        if (avatarAnimator == null) return;

        float dt = Time.deltaTime;
        float s  = lerpSpeed * dt;

        headTilt  = Mathf.Lerp(headTilt,  targetHeadTilt  * motionIntensity, s);
        eyeFocus  = Mathf.Lerp(eyeFocus,  targetEyeFocus,  s);
        posture   = Mathf.Lerp(posture,   targetPosture,   s);
        blinkRate = Mathf.Lerp(blinkRate, targetBlinkRate, s);
        microMove = Mathf.Lerp(microMove, targetMicroMove, s);
        smile     = Mathf.Lerp(smile,     targetSmile,     s);

        // Gaze: focused → locked; unfocused → slow procedural drift so the
        // eyes never look dead-stiff between frames (still reaction-driven).
        gazeDrift = Mathf.Lerp(gazeDrift, (1f - eyeFocus) * 0.04f, s);
        float gazeX = Mathf.Sin(Time.time * 0.35f) * gazeDrift;
        float gazeY = Mathf.Sin(Time.time * 0.28f) * gazeDrift;

        // STEALTH → almost no movement (doc: MicroMovement 0.0 in STEALTH).
        float movementScale = (currentMode == "STEALTH") ? 0.15f : 1f;

        avatarAnimator.SetFloat("HeadTilt",      headTilt);
        avatarAnimator.SetFloat("EyeFocus",      eyeFocus);
        avatarAnimator.SetFloat("Posture",       posture);
        avatarAnimator.SetFloat("BlinkRate",     blinkRate);
        avatarAnimator.SetFloat("MicroMovement", microMove * movementScale);
        avatarAnimator.SetFloat("GazeX",         gazeX);
        avatarAnimator.SetFloat("GazeY",         gazeY);
        avatarAnimator.SetFloat("Smile",         smile);

        if (smileRenderer != null)
            smileRenderer.SetBlendShapeWeight(smileBlendShapeIndex, smile * 100f);
    }
}

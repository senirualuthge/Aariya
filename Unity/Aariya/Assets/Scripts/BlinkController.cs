using UnityEngine;
using System.Collections;

// BUG #16 FIX: the document's close-eye loop was truncated mid-execution
// (the Flutter directory listing was injected into the C# file around line 953).
// The Mathf.Lerp arguments, yield return null, and closing braces were all
// missing. Reconstructed from the open-eye mirror and the documented algorithm.

public class BlinkController : MonoBehaviour
{
    [Header("Configuration")]
    public SkinnedMeshRenderer faceRenderer;
    public int blinkBlendShapeIndex = 0;  // Set in Inspector per-avatar

    public float minBlinkInterval = 2.0f; // seconds between blinks
    public float maxBlinkInterval = 6.0f;
    public float blinkDuration    = 0.15f;

    [Header("AI Control")]
    [Range(0.5f, 2.0f)]
    public float blinkRateMultiplier = 1.0f;  // Set by AIStateReceiver

    private float nextBlinkTime;
    private bool  isBlinking = false;

    void Start()  { ScheduleNextBlink(); }

    void Update()
    {
        if (!isBlinking && Time.time >= nextBlinkTime)
            StartCoroutine(BlinkRoutine());
    }

    void ScheduleNextBlink()
    {
        float interval = Random.Range(minBlinkInterval, maxBlinkInterval)
                         / blinkRateMultiplier;
        nextBlinkTime = Time.time + interval;
    }

    IEnumerator BlinkRoutine()
    {
        isBlinking = true;
        float half = blinkDuration / 2f;

        // ── Close eye (0 → 100) ──────────────────────────────────────────────
        // BUG #16 FIX: this entire block was missing from the document
        for (float t = 0; t < half; t += Time.deltaTime)
        {
            float weight = Mathf.Lerp(0f, 100f, t / half);
            faceRenderer?.SetBlendShapeWeight(blinkBlendShapeIndex, weight);
            yield return null;
        }
        faceRenderer?.SetBlendShapeWeight(blinkBlendShapeIndex, 100f);

        // ── Open eye (100 → 0) ───────────────────────────────────────────────
        for (float t = 0; t < half; t += Time.deltaTime)
        {
            float weight = Mathf.Lerp(100f, 0f, t / half);
            faceRenderer?.SetBlendShapeWeight(blinkBlendShapeIndex, weight);
            yield return null;
        }
        faceRenderer?.SetBlendShapeWeight(blinkBlendShapeIndex, 0f);

        isBlinking = false;
        ScheduleNextBlink();
    }
}
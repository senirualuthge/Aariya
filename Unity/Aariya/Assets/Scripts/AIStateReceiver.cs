using UnityEngine;
using System;
using System.Text;
using System.Net.WebSockets;
using System.Threading;
using System.Threading.Tasks;
// BUG #17 FIX: Unity's JsonUtility cannot deserialize nested JSON objects.
// §6.3 used JsonUtility.FromJson<AIEmotionState>(json) on the full ServerOutput
// payload, which always produced zeroed values for brain_state.emotion_target.
// Fix: use Newtonsoft.Json (add via Unity Package Manager:
//   com.unity.nuget.newtonsoft-json) as documented in §6.5.
using Newtonsoft.Json.Linq;

public class AIStateReceiver : MonoBehaviour
{
    [Header("Connections")]
    public Animator       avatarAnimator;
    public BlinkController blinkController;

    [Header("WebSocket Settings")]
    // BUG #7 (Unity-side): endpoint is now /ws/brain (fixed in main.py too)
    public string wsUrl = "ws://localhost:8000/ws/brain";

    [Header("Smoothing Settings")]
    public float lerpSpeed = 5.0f;

    // ── Target values from JSON ───────────────────────────────────────────────
    private float targetMoodValence = 0f;
    private float targetEnergy      = 0.5f;
    private bool  targetIsAngry     = false;
    private float targetBlinkRate   = 1.0f;

    // ── Smoothed current values ───────────────────────────────────────────────
    private float currentMoodValence = 0f;
    private float currentEnergy      = 0.5f;

    private ClientWebSocket ws;

    async void Start()    { await ConnectWebSocket(); }

    async Task ConnectWebSocket()
    {
        ws = new ClientWebSocket();
        try
        {
            Debug.Log($"[Aariya] Connecting to {wsUrl}");
            await ws.ConnectAsync(new Uri(wsUrl), CancellationToken.None);
            Debug.Log("[Aariya] Connected to Python Brain!");

            var connMsg = "{\"type\":\"input.multimodal\",\"timestamp\":"
                          + DateTimeOffset.UtcNow.ToUnixTimeSeconds()
                          + ",\"lifecycle\":\"connect\"}";
            await ws.SendAsync(
                Encoding.UTF8.GetBytes(connMsg),
                WebSocketMessageType.Text, true, CancellationToken.None);

            _ = ReceiveLoop();
        }
        catch (Exception e)
        {
            Debug.LogError($"[Aariya] WebSocket failed: {e.Message}");
        }
    }

    async Task ReceiveLoop()
    {
        var buffer = new byte[8192];
        while (ws?.State == WebSocketState.Open)
        {
            try
            {
                var result = await ws.ReceiveAsync(
                    new ArraySegment<byte>(buffer), CancellationToken.None);
                if (result.MessageType == WebSocketMessageType.Text)
                {
                    string json = Encoding.UTF8.GetString(buffer, 0, result.Count);
                    ParseAndApply(json);
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[Aariya] Receive error: {e.Message}");
                break;
            }
        }
    }

    void ParseAndApply(string json)
    {
        // BUG #17 FIX: JsonUtility cannot handle nested JSON.
        // Use Newtonsoft.Json JObject to navigate brain_state.emotion_target.
        try
        {
            var root = JObject.Parse(json);

            // Support both wire protocols:
            //   §8  ServerOutput → brain_state.emotion_target
            //   §7.5 mobile response → emotion field (simple string)
            var et = root["brain_state"]?["emotion_target"];
            if (et != null)
            {
                targetMoodValence = et["valence"]?.Value<float>() ?? 0f;
                targetEnergy      = et["energy"]?.Value<float>()  ?? 0.5f;
                float anger       = et["anger"]?.Value<float>()   ?? 0f;
                targetIsAngry     = anger > 0.6f;
                targetBlinkRate   = 1.0f + (targetEnergy * 0.5f) + (anger * 0.5f);
            }
        }
        catch (Exception e)
        {
            Debug.LogWarning($"[Aariya] JSON parse error: {e.Message}");
        }
    }

    void Update()
    {
        if (avatarAnimator == null) return;

        currentMoodValence = Mathf.Lerp(currentMoodValence, targetMoodValence,
                                        Time.deltaTime * lerpSpeed);
        currentEnergy      = Mathf.Lerp(currentEnergy, targetEnergy,
                                        Time.deltaTime * lerpSpeed);

        avatarAnimator.SetFloat("MoodValence", currentMoodValence);
        avatarAnimator.SetFloat("Energy",      currentEnergy);
        avatarAnimator.SetBool ("IsAngry",     targetIsAngry);

        if (blinkController != null)
            blinkController.blinkRateMultiplier = Mathf.Lerp(
                blinkController.blinkRateMultiplier, targetBlinkRate,
                Time.deltaTime * lerpSpeed);
    }

    private async void OnDestroy()
    {
        if (ws != null)
        {
            try
            {
                await ws.CloseAsync(
                    WebSocketCloseStatus.NormalClosure, "Closing", CancellationToken.None);
            }
            catch { }
            ws.Dispose();
        }
    }
}
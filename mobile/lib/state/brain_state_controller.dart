import 'package:flutter/foundation.dart';

/// Live brain state for the Avatar Orb / Emotion Ring / voice overlay.
///
/// Mirrors the server's `BrainState` payload (`/ws/mobile` sends it as
/// `{ type: 'state.update', state: {...} }`) plus the transient UI flags
/// (thinking / speaking / listening) that drive the presence layer.
class BrainStateController with ChangeNotifier {
  // ── Continuous state (from server BrainState) ──────────────────────────────
  double trust = 0.5;
  double valence = 0.0;
  double arousal = 0.0;
  double attachment = 0.0;
  String activeMode = 'balanced';
  String emotion = 'neutral';

  // ── Transient UI flags ──────────────────────────────────────────────────────
  bool isThinking = false;
  bool isSpeaking = false;
  bool isListening = false;

  /// Idle-baseline for [energy] — the orb treats this as "resting".
  static const double idleEnergy = 0.4;

  // ── Orb energy (driven by audio engine / TTS) ──────────────────────────────
  double energy = idleEnergy;

  /// Last full AI response text (used by the voice overlay).
  String responseText = '';

  // ── Derived ─────────────────────────────────────────────────────────────────

  /// Emotional valence in [-1, 1] — from server when available, else mapped
  /// from the discrete emotion label.
  double get emotionValence {
    if (valence != 0.0) return valence.clamp(-1.0, 1.0);
    if (['joy', 'trust', 'excited', 'calm', 'warm', 'affectionate']
        .contains(emotion.toLowerCase())) {
      return 0.8;
    }
    if (['sadness', 'fear', 'anger', 'disgust', 'hurt', 'defensive']
        .contains(emotion.toLowerCase())) {
      return -0.8;
    }
    return 0.0;
  }

  /// TTS/audio energy normalized off the idle baseline (0..1): 0.4 → 0,
  /// 1.0 → 1.0. Used to drive the orb while Aariya speaks — shared by the
  /// home screen and the voice overlay so the baseline can never drift.
  double get speechEnergy {
    final e = energy;
    return ((e - idleEnergy) / (1 - idleEnergy)).clamp(0.0, 1.0);
  }

  /// Emotional arousal in [0, 1] — from server when available, else mapped
  /// from the discrete emotion label.
  double get emotionArousal {
    if (arousal != 0.0) return arousal.clamp(0.0, 1.0);
    if (['angry', 'excited', 'joy', 'surprise'].contains(emotion.toLowerCase())) {
      return 0.9;
    }
    if (['calm', 'sadness', 'trust', 'neutral'].contains(emotion.toLowerCase())) {
      return 0.2;
    }
    return 0.5;
  }

  // ── Updates ─────────────────────────────────────────────────────────────────

  /// Generic map update (legacy path).
  void updateFromMap(Map<String, dynamic> data) {
    _applyState(data);
  }

  /// Applies a server payload. Accepts the `state.update` envelope
  /// (`{ 'state': {...} }`), a `brain_state` block, or a flat state map.
  void updateFromServer(Map<String, dynamic> data) {
    final Map<String, dynamic>? envelope = data['state'] is Map
        ? Map<String, dynamic>.from(data['state'] as Map)
        : data['brain_state'] is Map
            ? Map<String, dynamic>.from(data['brain_state'] as Map)
            : null;

    if (envelope != null) {
      _applyState(envelope);
    } else {
      _applyState(data);
    }
  }

  void _applyState(Map<String, dynamic> data) {
    trust = (data['trust'] as num?)?.toDouble() ?? trust;
    valence = (data['valence'] as num?)?.toDouble() ?? valence;
    arousal = (data['arousal'] as num?)?.toDouble() ?? arousal;
    attachment =
        (data['attachment'] as num?)?.toDouble() ?? attachment;
    activeMode = data['current_mode'] as String? ?? data['mode'] as String? ??
        activeMode;
    emotion = data['emotion'] as String? ??
        data['emotional_state'] as String? ??
        emotion;

    final text = data['response_text'] as String? ?? data['text'] as String?;
    if (text != null && text.isNotEmpty) responseText = text;

    notifyListeners();
  }

  // ── Transient setters ───────────────────────────────────────────────────────

  void setThinking(bool value) {
    if (isThinking == value) return;
    isThinking = value;
    notifyListeners();
  }

  void setSpeaking(bool value) {
    if (isSpeaking == value) return;
    isSpeaking = value;
    notifyListeners();
  }

  void setListening(bool value) {
    if (isListening == value) return;
    isListening = value;
    notifyListeners();
  }

  /// Feeds an audio-energy sample into the orb during speech.
  void pulseEnergy(double sample) {
    energy = sample.clamp(0.0, 1.0);
    notifyListeners();
  }

  /// Clears transient state (interrupt / conversation end).
  void reset() {
    isThinking = false;
    isSpeaking = false;
    isListening = false;
    energy = idleEnergy;
    notifyListeners();
  }
}

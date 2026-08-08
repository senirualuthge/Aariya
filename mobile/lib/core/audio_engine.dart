import 'dart:async';
import 'dart:math' as math;

/// Audio playback engine for streaming TTS chunks from the backend.
///
/// Manages the energy stream that drives the Avatar Orb's pulse during speech.
/// When backend audio_chunk support lands (ElevenLabs / OpenAI stream),
/// `playChunk()` will decode and buffer the base64 audio frames.
class AudioEngine {
  // ── Energy stream ─────────────────────────────────────────────────────────
  final StreamController<double> _energyController =
      StreamController<double>.broadcast();

  Stream<double> get energyStream => _energyController.stream;

  // ── State ─────────────────────────────────────────────────────────────────
  bool isPlaying = false;
  Timer? _pulseTimer;
  int _frame = 0;

  // ── Playback ──────────────────────────────────────────────────────────────

  /// Called for each `audio_chunk` packet from the server.
  /// Simulates energy from chunk size; replace with real audio buffering
  /// when streaming TTS backend (ElevenLabs/OpenAI) is available.
  void playChunk(String base64Data) {
    isPlaying = true;
    final energy = (base64Data.length / 2000).clamp(0.3, 1.0);
    _energyController.add(energy);
  }

  /// Simulate energy pulses while local flutter_tts is speaking.
  /// Call this when TTS begins, [stop] when it ends.
  void startPulsing({Duration interval = const Duration(milliseconds: 100)}) {
    isPlaying = true;
    _frame = 0;
    _pulseTimer?.cancel();
    _pulseTimer = Timer.periodic(interval, (_) {
      if (!isPlaying) {
        _pulseTimer?.cancel();
        return;
      }
      // Sine-wave energy that mimics natural vocal cadence
      final energy = 0.45 + (math.sin(_frame * 0.45) * 0.38).abs();
      _energyController.add(energy.clamp(0.0, 1.0));
      _frame++;
    });
  }

  /// Stop playback and reset orb to idle energy baseline.
  void stop() {
    isPlaying = false;
    _pulseTimer?.cancel();
    _energyController.add(0.4); // idle baseline energy
  }

  void dispose() {
    _pulseTimer?.cancel();
    _energyController.close();
  }
}

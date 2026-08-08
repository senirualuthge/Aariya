import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import '../services/websocket_service.dart';
import '../services/webrtc_service.dart';

/// Conversation states matching the upgraded server-side state machine.
enum ConversationState {
  idle,
  listening,
  interrupting,
  processing,
  streaming,
  speaking,
  recovering,
}

/// ClientBrain acts as a semi-autonomous agent on the mobile side.
/// It predicts state transitions, handles failures, smooths latency,
/// and maintains conversational continuity even when the backend lags.
class ClientBrain extends ChangeNotifier {
  static final ClientBrain instance = ClientBrain._internal();
  ClientBrain._internal();

  // ─── State ────────────────────────────────────────────────────────────────
  ConversationState _state = ConversationState.idle;
  ConversationState get state => _state;

  String _lastEmotion = 'calm';
  String get lastEmotion => _lastEmotion;

  double get emotionValence => _getValence(_lastEmotion);
  double get emotionArousal => _getArousal(_lastEmotion);
  double get energy => _getArousal(_lastEmotion) * 0.8;

  double _trustEstimate = 0.5;
  double get trustEstimate => _trustEstimate;

  // ─── Short-term cache (local memory) ─────────────────────────────────────
  final List<Map<String, String>> _recentMessages = [];
  List<Map<String, String>> get recentMessages =>
      List.unmodifiable(_recentMessages);

  // ─── Interrupt flag ────────────────────────────────────────────────────────
  bool _interrupted = false;
  bool get interrupted => _interrupted;

  // ─── Latency masking timer ────────────────────────────────────────────────
  Timer? _thinkingTimer;

  // ──────────────────────────────────────────────────────────────────────────
  // PUBLIC API
  // ──────────────────────────────────────────────────────────────────────────

  /// Initiate connection to Backend services
  Future<void> connect(String serverIp) async {
    // 1. Start MultiSocket API
    await WebSocketService.instance.connect();
    
    // 2. Initialize and start WebRTC Voice stream
    await WebRTCService.instance.init();
    await WebRTCService.instance.start(serverIp);

    // Listen to WebSocket status changes for ClientBrain degradation handling
    WebSocketService.instance.isConnected.addListener(() {
      if (WebSocketService.instance.isConnected.value) {
        onConnectionRestored();
      } else {
        onConnectionLost();
      }
    });
  }

  /// Called when the user starts/finishes speaking (VAD triggers).
  void onUserStartedSpeaking() {
    _interrupted = true;
    _thinkingTimer?.cancel();
    _transition(ConversationState.listening);
  }

  /// Called when the VAD signals the user has stopped speaking.
  /// Immediately fakes a "thinking" state for latency masking.
  void onUserFinishedSpeaking(String transcript) {
    _storeMessage('user', transcript);
    _transition(ConversationState.processing);

    // Latency masking: show thinking animation before server responds
    _thinkingTimer = Timer(const Duration(milliseconds: 80), () {
      if (_state == ConversationState.processing) {
        notifyListeners(); // triggers orb pulse / "Hmm…" animation
      }
    });
  }

  /// Called when the first streaming token arrives from the server.
  void onStreamStart() {
    _thinkingTimer?.cancel();
    _interrupted = false;
    _transition(ConversationState.streaming);
  }

  /// Called as each streaming token arrives.
  void onStreamToken(String token) {
    // Triggers incremental text rendering notification
    notifyListeners();
  }

  /// Called when streaming is complete and audio playback begins.
  void onSpeakingStart(String fullResponse, String emotion) {
    _storeMessage('ai', fullResponse);
    _lastEmotion = emotion;

    // Predictive emotion smoothing (lerp toward server-provided emotion)
    _updateTrustSmoothing();
    _transition(ConversationState.speaking);
  }

  /// Called when AI finishes speaking.
  void onSpeakingEnd() {
    _transition(ConversationState.idle);
  }

  /// Called on WebSocket disconnect / error — enter degraded mode.
  void onConnectionLost() {
    _thinkingTimer?.cancel();
    _transition(ConversationState.recovering);
  }

  /// Called when connection is restored.
  void onConnectionRestored() {
    _transition(ConversationState.idle);
  }

  /// Triggers an interrupt (barge-in) signal.
  void interrupt(String serverIp) {
    _interrupted = true;
    _thinkingTimer?.cancel();
    _transition(ConversationState.interrupting);

    // Stop WebSocket backend processing explicitly without losing connection
    WebSocketService.instance.sendInterrupt();
  }

  /// Dispatches remote control override commands
  void sendRemoteCommand(String action, [Map<String, dynamic>? data]) {
    final payload = {
      'type': 'command',
      'action': action,
      if (data != null) ...data,
    };
    WebSocketService.instance.sendMessage(jsonEncode(payload));
  }

  // ──────────────────────────────────────────────────────────────────────────
  // PRIVATE HELPERS
  // ──────────────────────────────────────────────────────────────────────────

  void _transition(ConversationState next) {
    if (_state == next) return;
    _state = next;
    notifyListeners();
  }

  void _storeMessage(String role, String text) {
    _recentMessages.add({'role': role, 'text': text});
    // Keep last 10 messages for local context
    if (_recentMessages.length > 10) _recentMessages.removeAt(0);
  }

  void _updateTrustSmoothing() {
    // Smooth trust upward on successful interaction
    _trustEstimate = (_trustEstimate + 0.02).clamp(0.0, 1.0);
  }

  double _getValence(String emotion) {
    if (['joy', 'trust', 'excited', 'calm'].contains(emotion)) return 0.8;
    if (['sadness', 'fear', 'anger', 'disgust'].contains(emotion)) return -0.8;
    return 0.0;
  }

  double _getArousal(String emotion) {
    if (['angry', 'excited', 'joy', 'surprise'].contains(emotion)) return 0.9;
    if (['calm', 'sadness', 'trust'].contains(emotion)) return 0.2;
    return 0.5;
  }

  @override
  void dispose() {
    _thinkingTimer?.cancel();
    WebSocketService.instance.dispose();
    WebRTCService.instance.stop();
    super.dispose();
  }
}

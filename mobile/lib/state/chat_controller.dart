import 'package:flutter/foundation.dart';
import 'package:flutter_tts/flutter_tts.dart';
import '../models/message.dart';
import '../services/websocket_service.dart';
import '../state/brain_state_controller.dart';
import '../core/audio_engine.dart';

/// Central state controller for the conversation.
///
/// Integrates:
/// - Streaming text reconstruction (thinking → text.stream → state.update)
/// - FIXV3 brain state (emotion valence/arousal, trust, energy)
/// - TTS playback with energy simulation for the Avatar Orb
/// - Interrupt handling (both sending and receiving)
///
/// Shared as a singleton: every screen (Orb, Chat, voice overlay) must talk
/// through [ChatController.instance] so a single TTS engine and single brain
/// state drive the whole app — otherwise the same AI reply gets spoken twice.
class ChatController extends ChangeNotifier {
  static final ChatController instance = ChatController._internal();

  /// Isolated instance for tests.
  factory ChatController() => ChatController._internal();

  ChatController._internal() {
    _initTts();
    _listenToWebSocket();
    _listenToAudioEnergy();
  }

  // ── Message list ──────────────────────────────────────────────────────────
  final List<Message> _messages = [];
  List<Message> get messages => List.unmodifiable(_messages);

  // ── Sub-systems ───────────────────────────────────────────────────────────
  final FlutterTts _flutterTts = FlutterTts();
  final BrainStateController brain = BrainStateController();
  final AudioEngine audioEngine = AudioEngine();

  // ── Streaming state ───────────────────────────────────────────────────────
  String _currentStreamText = '';
  String? _currentStreamMessageId;

  // ── Public state ──────────────────────────────────────────────────────────
  bool get isThinking => brain.isThinking;

  /// Fired when TTS finishes speaking a response. Used by voice overlay.
  VoidCallback? onTtsCompletion;

  /// Last command the server refused (`command_denied` frame). Null when no
  /// denial has been seen. Consumers (chat screen) listen and surface it.
  final ValueNotifier<String?> commandDenied = ValueNotifier<String?>(null);

  // ─────────────────────────────────────────────────────────────────────────

  Future<void> _initTts() async {
    // TTS is a best-effort enhancement — a missing/unsupported engine on the
    // device must never crash the conversation flow.
    try {
      await _flutterTts.setLanguage("en-US");
      await _flutterTts.setSpeechRate(0.48);
      await _flutterTts.setVolume(1.0);
      await _flutterTts.setPitch(1.1);
    } catch (e) {
      debugPrint('[TTS] init failed: $e');
    }

    _flutterTts.setStartHandler(() {
      audioEngine.startPulsing();
      brain.setSpeaking(true);
    });

    _flutterTts.setCompletionHandler(() {
      audioEngine.stop();
      brain.setSpeaking(false);
      brain.setListening(true);
      onTtsCompletion?.call();
    });

    _flutterTts.setCancelHandler(() {
      audioEngine.stop();
      brain.setSpeaking(false);
    });
  }

  void _listenToAudioEnergy() {
    audioEngine.energyStream.listen((energy) {
      brain.pulseEnergy(energy);
    });
  }

  void _listenToWebSocket() {
    WebSocketService.instance.messagesStream.listen((data) {
      final type = data['type'] as String? ?? '';

      switch (type) {
        // ── AI is thinking (latency mask) ──────────────────────────────────
        case 'thinking':
          _handleThinking();
          break;

        // ── Token chunk arriving ──────────────────────────────────────────
        case 'text.stream':
          _handleTextStream(data);
          break;

        // ── Full state update (response complete) ─────────────────────────
        case 'state.update':
          _handleStateUpdate(data);
          break;

        // ── Server acknowledged interrupt ─────────────────────────────────
        case 'interrupted':
          _handleInterrupted();
          break;

        // ── Zero-Interference: server refused an authority-only command ────
        case 'command_denied':
          commandDenied.value =
              (data['action'] as String? ?? 'command').replaceAll('_', ' ');
          break;

        // ── Streaming audio chunk ─────────────────────────────────────────
        case 'audio_chunk':
          final chunkData = data['data'] as String? ?? '';
          if (chunkData.isNotEmpty) audioEngine.playChunk(chunkData);
          break;

        // ── Response fully done ───────────────────────────────────────────
        case 'response_end':
          _finalizeStreamingMessage(data);
          break;

        // ── Legacy / fallback ─────────────────────────────────────────────
        default:
          final text = data['response_text'] ?? data['text'];
          if (text != null && (text as String).isNotEmpty) {
            _handleLegacyResponse(data, text);
          }
      }
    });
  }

  // ── Event handlers ────────────────────────────────────────────────────────

  void _handleThinking() {
    _currentStreamText = '';
    _currentStreamMessageId =
        DateTime.now().millisecondsSinceEpoch.toString();

    _addMessage(Message(
      id: _currentStreamMessageId!,
      text: '',
      isUser: false,
      timestamp: DateTime.now().millisecondsSinceEpoch,
    ));

    brain.setThinking(true);
    notifyListeners();
  }

  void _handleTextStream(Map<String, dynamic> data) {
    final chunk = data['chunk'] as String? ?? '';
    _currentStreamText += chunk;
    brain.setThinking(false);

    if (_currentStreamMessageId != null) {
      final idx =
          _messages.indexWhere((m) => m.id == _currentStreamMessageId);
      if (idx != -1) {
        _messages[idx] = _messages[idx].copyWith(text: _currentStreamText);
        notifyListeners();
      }
    }
  }

  void _handleStateUpdate(Map<String, dynamic> data) {
    // Update brain state from FIXV3 payload
    brain.updateFromServer(data);
    brain.setThinking(false);

    final finalText =
        (data['response_text'] as String? ?? '').isNotEmpty
            ? data['response_text'] as String
            : _currentStreamText;

    _finalizeWithText(finalText, data);
  }

  void _handleInterrupted() {
    // Clear any in-progress streaming placeholder
    if (_currentStreamMessageId != null) {
      _messages.removeWhere((m) => m.id == _currentStreamMessageId);
      _currentStreamMessageId = null;
      _currentStreamText = '';
    }
    brain.reset();
    brain.setListening(true);
    notifyListeners();
  }

  void _handleLegacyResponse(Map<String, dynamic> data, String text) {
    brain.updateFromServer(data);
    _finalizeWithText(text, data);
  }

  void _finalizeStreamingMessage(Map<String, dynamic> data) {
    final text = data['response_text'] as String? ?? _currentStreamText;
    _finalizeWithText(text, data);
  }

  void _finalizeWithText(String text, Map<String, dynamic> data) {
    if (_currentStreamMessageId != null) {
      final idx =
          _messages.indexWhere((m) => m.id == _currentStreamMessageId);
      if (idx != -1 && text.isNotEmpty) {
        _messages[idx] = _messages[idx].copyWith(
          text: text,
          emotion: _extractEmotion(data),
        );
      }
      _currentStreamMessageId = null;
    } else if (text.isNotEmpty) {
      _addMessage(Message(
        id: data['turn_id'] as String? ??
            DateTime.now().millisecondsSinceEpoch.toString(),
        text: text,
        isUser: false,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        emotion: _extractEmotion(data),
      ));
    }

    if (text.isNotEmpty) {
      brain.setSpeaking(true);
      _flutterTts.speak(text);
    }

    notifyListeners();
  }

  String? _extractEmotion(Map<String, dynamic> data) {
    return data['brain_state']?['emotional_state'] as String? ??
        data['state']?['emotion'] as String? ??
        data['emotion'] as String?;
  }

  // ── Public API ────────────────────────────────────────────────────────────

  void sendMessage(String text, {String? base64Image}) {
    if (text.trim().isEmpty) return;

    _addMessage(Message(
      id: DateTime.now().millisecondsSinceEpoch.toString(),
      text: text,
      isUser: true,
      timestamp: DateTime.now().millisecondsSinceEpoch,
    ));

    brain.setListening(false);
    WebSocketService.instance.sendMessage(text, base64Image: base64Image);
  }

  /// Interrupt the AI mid-response.
  void sendInterrupt() {
    _flutterTts.stop();
    audioEngine.stop();
    WebSocketService.instance.sendInterrupt();
   // Optimistic local clear — server will confirm with 'interrupted'
    _handleInterrupted();
  }

  Future<void> stopSpeaking() async {
    await _flutterTts.stop();
    audioEngine.stop();
    brain.setSpeaking(false);
  }

  void _addMessage(Message message) {
    _messages.add(message);
    notifyListeners();
  }

  @override
  void dispose() {
    _flutterTts.stop();
    audioEngine.dispose();
    brain.dispose();
    commandDenied.dispose();
    super.dispose();
  }
}

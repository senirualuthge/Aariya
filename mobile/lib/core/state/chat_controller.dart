import 'package:flutter/foundation.dart';
import '../models/message.dart';
import '../services/websocket_service.dart';
import 'brain_state_controller.dart';

/// Central state controller for the conversation.
///
/// Integrates:
/// - Streaming text reconstruction (thinking → text.stream → state.update)
/// - FIXV3 brain state (emotion valence/arousal, trust, energy)
/// - Interrupt handling (both sending and receiving)
///
/// Text-only by design: the voice/TTS pipeline was removed (server and
/// client). Replies are shown as text; no speech synthesis runs here.
///
/// Shared as a singleton: every screen (Orb, Chat) must talk through
/// [ChatController.instance] so a single brain state drives the whole app.
class ChatController extends ChangeNotifier {
  static final ChatController instance = ChatController._internal();

  /// Isolated instance for tests.
  factory ChatController() => ChatController._internal();

  ChatController._internal() {
    _listenToWebSocket();
  }

  // ── Message list ──────────────────────────────────────────────────────────
  final List<Message> _messages = [];
  List<Message> get messages => List.unmodifiable(_messages);

  // ── Sub-systems ───────────────────────────────────────────────────────────
  final BrainStateController brain = BrainStateController();

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

        // ── Streaming audio chunk ───────────────────────────────────────
        // Voice/TTS pipeline was removed; audio frames no longer exist.
        case 'audio_chunk':
        case 'audio.chunk':
        case 'audio.done':
          break;

        // ── Response fully done ───────────────────────────────────────────
        case 'response_end':
          _finalizeStreamingMessage(data);
          break;

        // ── Avatar events (Gap 15) ──────────────────────────────────────
        case 'avatar.emotion':
          // Server-side blendshape weights received
          final emotion = data['emotion'] as String? ?? 'neutral';
          final intensity = (data['intensity'] as num?)?.toDouble() ?? 0.5;
          brain.updateFromServer({
            'emotion': emotion,
            'valence': intensity,
          });
          break;

        case 'avatar.idle':
          // Gap 4: Idle behavior animation
          break;

        // ── Brain response with trust/contradiction metadata ────────────
        case 'brain.response':
          _handleBrainResponse(data);
          break;

        // ── Kill-switch / feature-flag sync from server ─────────────────
        case 'killswitch.update':
          brain.applyKillSwitchUpdate(data);
          break;

        // ── Voice pipeline events (barge-in, speech start/end) ──────────
        case 'voice.event':
          _handleVoiceEvent(data);
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

  void _handleBrainResponse(Map<String, dynamic> data) {
    // Sync server trust to brain controller
    final trust = data['trust'];
    final language = data['language'] as String?;
    if (trust is num) {
      brain.updateFromServer({
        'trust': trust.toDouble(),
        'emotion': data['emotion'],
        'response_text': data['text'],
      });
    }
    // Store detected language (informational; no TTS switching anymore)
    if (language != null && language.isNotEmpty) {
      debugPrint('[ChatController] Server detected language: $language');
    }
    // Legacy path: finalize with text
    final text = data['text'] as String? ?? '';
    if (text.isNotEmpty) {
      _finalizeWithText(text, data);
    }
  }

  void _handleVoiceEvent(Map<String, dynamic> data) {
    final event = data['event'] as String? ?? '';
    switch (event) {
      case 'barge_in':
        sendInterrupt();
        break;
      case 'speech_start':
        brain.setListening(true);
        break;
      case 'speech_end':
        brain.setListening(false);
        break;
      case 'listening':  // Server signals ready for user input
        brain.setSpeaking(false);
        brain.setListening(true);
        break;
    }
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
    WebSocketService.instance.sendInterrupt();
   // Optimistic local clear — server will confirm with 'interrupted'
    _handleInterrupted();
  }

  Future<void> stopSpeaking() async {
    brain.setSpeaking(false);
  }

  void _addMessage(Message message) {
    _messages.add(message);
    notifyListeners();
  }

  @override
  void dispose() {
    brain.dispose();
    commandDenied.dispose();
    super.dispose();
  }
}

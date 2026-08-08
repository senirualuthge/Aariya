import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'ack_outbox.dart';
import 'server_config.dart';

/// Multi-channel WebSocket client for the Aariya mobile app.
///
/// Manages three independent channels to the Python backend:
///   - chat      `/ws/mobile`           → conversation (text.stream / ai_response
///                                        / state.update / inner_thought / interrupt_ack)
///   - control   `/ws/mobile/control`   → command overrides, ping/pong
///   - analytics `/ws/mobile/analytics` → 1 Hz system + brain metrics heartbeat
///
/// [messagesStream] merges the chat + control channels (decoded Maps);
/// [analyticsStream] carries analytics frames. [isConnected] tracks the
/// chat channel state and drives the UI's offline banner.
///
/// The backend address is resolved through [ServerConfig] (persisted overrides
/// take precedence over `--dart-define`). If the chat channel drops the client
/// automatically reconnects with exponential backoff.
///
/// Reliable messages (user input, interrupts, commands) are routed through an
/// [AckOutbox]: they carry a unique `id` + `requires_ack`, are retried with
/// exponential backoff until the server ACKs them, and the client enters a
/// degraded state after repeated failures (see [isDegraded]).
class WebSocketService {
  static final WebSocketService instance = WebSocketService._();
  WebSocketService._();

  // ── Channels ────────────────────────────────────────────────────────────────
  WebSocketChannel? _chatChannel;
  WebSocketChannel? _controlChannel;
  WebSocketChannel? _analyticsChannel;

  // ── Reliable-message outbox (Protocol v2 ACK/retry) ───────────────────────
  final AckOutbox _outbox = AckOutbox();

  /// True when a reliable message was dropped after exhausting retries.
  ValueNotifier<bool> get isDegraded => _outbox.isDegraded;

  /// Number of messages currently awaiting a server ACK.
  int get pendingMessageCount => _outbox.pendingCount;

  // ── Public streams ──────────────────────────────────────────────────────────
  final StreamController<Map<String, dynamic>> _messagesController =
      StreamController<Map<String, dynamic>>.broadcast();
  final StreamController<Map<String, dynamic>> _analyticsController =
      StreamController<Map<String, dynamic>>.broadcast();

  Stream<Map<String, dynamic>> get messagesStream => _messagesController.stream;

  /// Backward-compatible alias used by the legacy control screen.
  Stream<Map<String, dynamic>> get stream => messagesStream;

  Stream<Map<String, dynamic>> get analyticsStream =>
      _analyticsController.stream;

  // ── Connection state ────────────────────────────────────────────────────────
  final ValueNotifier<bool> isConnected = ValueNotifier<bool>(false);

  Future<void>? _connectFuture;
  bool _disposed = false;

  // ── Auto-reconnect (exponential backoff) ───────────────────────────────────
  static const Duration _initialBackoff = Duration(seconds: 2);
  static const Duration _maxBackoff = Duration(seconds: 30);
  Timer? _reconnectTimer;
  int _reconnectAttempt = 0;

  // ── Connection management ───────────────────────────────────────────────────

  /// Opens the chat (default or [url]), control and analytics channels.
  ///
  /// Idempotent — repeated calls while connected/connecting return the same
  /// pending future instead of clobbering the active connection.
  Future<void> connect([String? url]) {
    if (_disposed) return Future.error(StateError('WebSocketService disposed'));
    if (isConnected.value || _connectFuture != null) {
      return _connectFuture ?? Future.value();
    }

    _reconnectTimer?.cancel();
    _reconnectTimer = null;

    final completer = Completer<void>();
    _connectFuture = completer.future;

    try {
      final baseUri = _resolveBase(url);
      _openChat('ws://${baseUri.host}:${baseUri.port}/ws/mobile');
      _openControl('ws://${baseUri.host}:${baseUri.port}/ws/mobile/control');
      _openAnalytics('ws://${baseUri.host}:${baseUri.port}/ws/mobile/analytics');
    } catch (e) {
      debugPrint('[WS] connect failed: $e');
      isConnected.value = false;
    }

    // Optimistically mark connected; listeners update the notifier on
    // first frame / error / close. Completing early keeps `await connect()`
    // (bootstrap / app init) from hanging when the backend is offline.
    isConnected.value = true;
    completer.complete();
    return completer.future;
  }

  /// Tears down the current channels and reconnects to the (possibly changed)
  /// address in [ServerConfig]. Used after the user edits the server address —
  /// unlike [dispose] the streams and notifiers stay alive.
  Future<void> reconnectToNewServer() async {
    if (_disposed) return;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    _reconnectAttempt = 0;
    try {
      _chatChannel?.sink.close();
      _controlChannel?.sink.close();
      _analyticsChannel?.sink.close();
    } catch (_) {}
    _chatChannel = null;
    _controlChannel = null;
    _analyticsChannel = null;
    _connectFuture = null;
    isConnected.value = false;
    await connect();
    // Anything queued while we were offline should be re-delivered now.
    _outbox.flush();
  }

  Uri _resolveBase(String? url) {
    if (url != null && url.isNotEmpty) return Uri.parse(url);
    return Uri.parse(ServerConfig.instance.wsBase);
  }

  void _openChat(String url) {
    final channel = WebSocketChannel.connect(Uri.parse(url));
    _chatChannel = channel;
    _subscribeChannel(channel, _messagesController, onError: () {
      isConnected.value = false;
      _scheduleReconnect();
    }, onDone: () {
      isConnected.value = false;
      _connectFuture = null;
      _scheduleReconnect();
    }, onFrame: () {
      if (_reconnectAttempt > 0) {
        debugPrint('[WS] reconnected after $_reconnectAttempt attempt(s)');
        _outbox.flush();
      }
      _reconnectAttempt = 0;
    });
  }

  void _openControl(String url) {
    final channel = WebSocketChannel.connect(Uri.parse(url));
    _controlChannel = channel;
    _subscribeChannel(channel, _messagesController, onError: () {
      _scheduleReconnect();
    }, onDone: () {
      _scheduleReconnect();
    });
  }

  void _openAnalytics(String url) {
    final channel = WebSocketChannel.connect(Uri.parse(url));
    _analyticsChannel = channel;
    _subscribeChannel(channel, _analyticsController);
  }

  void _subscribeChannel(
    WebSocketChannel channel,
    StreamController<Map<String, dynamic>> controller, {
    VoidCallback? onError,
    VoidCallback? onDone,
    VoidCallback? onFrame,
  }) {
    channel.stream.listen(
      (raw) {
        if (_disposed) return;
        final decoded = _decodeFrame(raw);
        if (decoded == null) return;

        final type = decoded['type'] as String? ?? '';

        // ── Protocol v2 ACK handling ───────────────────────────────────────
        if (type == 'ack') {
          final id = decoded['id'] as String?;
          if (id != null) _outbox.ack(id);
          onFrame?.call();
          return; // transport-level frame — not surfaced to the UI stream
        }
        if (type == 'interrupt_ack') {
          // Server acks interrupts without echoing an id — clear them all.
          _outbox.clearByType('interrupt');
        }

        onFrame?.call();
        controller.add(decoded);
      },
      onError: (Object e) {
        debugPrint('[WS] channel error: $e');
        onError?.call();
      },
      onDone: () {
        debugPrint('[WS] channel closed');
        onDone?.call();
      },
      cancelOnError: true,
    );
  }

  /// Reconnects with exponential backoff if a live channel dropped.
  void _scheduleReconnect() {
    if (_disposed) return;
    if (_reconnectTimer != null) return;

    final attempt = _reconnectAttempt++;
    final backoff = _initialBackoff * (1 << attempt.clamp(0, 4));
    final delay = backoff > _maxBackoff ? _maxBackoff : backoff;

    debugPrint('[WS] scheduling reconnect in ${delay.inSeconds}s');
    _reconnectTimer = Timer(delay, () {
      _reconnectTimer = null;
      if (_disposed) return;

      // Tear down whatever survived, then reconnect.
      try {
        _chatChannel?.sink.close();
        _controlChannel?.sink.close();
        _analyticsChannel?.sink.close();
      } catch (_) {}
      _chatChannel = null;
      _controlChannel = null;
      _analyticsChannel = null;
      _connectFuture = null;
      isConnected.value = false;

      connect();
    });
  }

  Map<String, dynamic>? _decodeFrame(dynamic raw) {
    try {
      if (raw is Map) {
        return Map<String, dynamic>.from(raw);
      }
      if (raw is String) {
        final decoded = jsonDecode(raw);
        if (decoded is Map) return Map<String, dynamic>.from(decoded);
      }
    } catch (e) {
      debugPrint('[WS] unparseable frame: $e');
    }
    return null;
  }

  // ── Sending ─────────────────────────────────────────────────────────────────

  /// Test seam: inject a frame into the shared messages stream exactly as if
  /// it had arrived from the server. Routes through the same stream that
  /// [ChatController] listens on, so widget tests can drive the full frame
  /// handling path (e.g. a `command_denied` frame) without a live socket.
  @visibleForTesting
  void emitTestFrame(Map<String, dynamic> frame) {
    _messagesController.add(frame);
  }

  /// Sends a message to the backend (reliably — tracked by the outbox).
  ///
  /// - Plain text (optionally with a base64 image) is wrapped in the mobile
  ///   chat protocol (`input.multimodal`) and routed to the chat channel.
  /// - JSON envelopes carrying a recognised `type` are routed to the control
  ///   channel (commands / remote_input / ping) or the chat channel (anything
  ///   else, e.g. an already-encoded brain payload).
  void sendMessage(String message, {String? base64Image}) {
    if (_disposed) return;

    if (base64Image != null) {
      _sendChatReliable({
        'type': 'input.multimodal',
        'content': message,
        'mode': 'voice',
        'image': base64Image,
      });
      return;
    }

    final Map<String, dynamic>? envelope = _tryParseJson(message);
    if (envelope != null) {
      final type = envelope['type'] as String? ?? '';
      if (_isControlType(type)) {
        _sendControlReliable(envelope);
      } else {
        _sendChatReliable(envelope);
      }
      return;
    }

    _sendChatReliable({
      'type': 'input.multimodal',
      'content': message,
      'mode': 'voice',
    });
  }

  /// Sends a barge-in interrupt to the active conversation (reliably).
  void sendInterrupt() {
    if (_disposed) return;
    _sendChatReliable({'type': 'interrupt'});
  }

  /// Sends a keepalive ping on the control channel; the server replies `pong`.
  ///
  /// Pings are intentionally NOT tracked by the outbox — they are heartbeats
  /// consumed by [ConnectionMonitor], and a lost ping is detected via timeout.
  void sendPing() {
    if (_disposed) return;
    _sendControl({'type': 'ping'});
  }

  // ── Internals ───────────────────────────────────────────────────────────────

  void _sendChatReliable(Map<String, dynamic> payload) {
    _outbox.enqueue(payload, (envelope) {
      _chatChannel?.sink.add(jsonEncode(envelope));
    });
  }

  void _sendControlReliable(Map<String, dynamic> payload) {
    _outbox.enqueue(payload, (envelope) {
      _controlChannel?.sink.add(jsonEncode(envelope));
    });
  }

  void _sendControl(Map<String, dynamic> payload) {
    final channel = _controlChannel;
    if (channel == null) return;
    channel.sink.add(jsonEncode(payload));
  }

  static bool _isControlType(String type) {
    return const {
      'command',
      'remote_input',
      'input.multimodal',
      'ping',
      'interrupt',
    }.contains(type);
  }

  Map<String, dynamic>? _tryParseJson(String raw) {
    final trimmed = raw.trim();
    if (trimmed.isEmpty) return null;
    if (!trimmed.startsWith('{')) return null;
    try {
      final decoded = jsonDecode(trimmed);
      return decoded is Map ? Map<String, dynamic>.from(decoded) : null;
    } catch (_) {
      return null;
    }
  }

  /// Closes every channel and releases resources. Safe to call multiple times.
  void dispose() {
    if (_disposed) return;
    _disposed = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    try {
      _chatChannel?.sink.close();
      _controlChannel?.sink.close();
      _analyticsChannel?.sink.close();
    } catch (_) {}
    _chatChannel = null;
    _controlChannel = null;
    _analyticsChannel = null;
    _outbox.dispose();
    _messagesController.close();
    _analyticsController.close();
    isConnected.dispose();
    _connectFuture = null;
  }
}

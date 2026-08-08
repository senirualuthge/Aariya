import 'dart:async';

import 'package:flutter/foundation.dart';

/// A reliable-message outbox for the mobile WebSocket protocol (Protocol v2).
///
/// Solves the "fire-and-forget" problem documented in `*Mobile Achi v2.txt`:
/// without an ACK contract, user input / commands can be silently lost and
/// produce ghost states on reconnect. This class implements the client half:
///
///   * every reliable send gets a unique `id` + `requires_ack: true`
///   * the message is tracked until the server echoes `{ "type": "ack",
///     "id": same-id }` back
///   * unacked messages are re-sent with **per-message exponential backoff**
///     (500ms → 1s → 2s …) — each pending message owns its own retry timer,
///     so a fast message never drags a slow one into an early drop
///   * after [maxRetries] failed attempts a message is dropped and the
///     outbox enters a **degraded** state (visible via [isDegraded])
///   * [flush] re-sends everything immediately when the connection is
///     restored, so no context is lost across reconnects
///
/// The class is transport-agnostic: the caller supplies a `send` closure per
/// message (the channel the message must travel on). This keeps it fully
/// unit-testable with `package:fake_async` — no sockets required.
class AckOutbox {
  AckOutbox({
    this.retryBase = const Duration(milliseconds: 500),
    this.maxRetries = 3,
  });

  /// Base backoff interval. Attempt N waits `retryBase << N`.
  final Duration retryBase;

  /// Number of failed retries after which a message is dropped.
  final int maxRetries;

  final Map<String, _PendingMessage> _pending = {};

  /// True when at least one message was dropped after exhausting retries.
  /// Cleared automatically once pending delivery recovers (the queue empties
  /// via successful ACKs).
  final ValueNotifier<bool> isDegraded = ValueNotifier<bool>(false);

  bool _disposed = false;
  int _seq = 0;

  /// Number of messages currently awaiting an ACK.
  int get pendingCount => _pending.length;

  /// True while there is at least one unacked message.
  bool get hasPending => _pending.isNotEmpty;

  /// Stamps [payload] with a fresh `id` + `requires_ack: true`, sends it
  /// immediately via [send], and tracks it for retry until acked.
  ///
  /// Returns the generated message id (useful for logging / correlation).
  String enqueue(
    Map<String, dynamic> payload,
    void Function(Map<String, dynamic> envelope) send,
  ) {
    final id = _nextId();
    final envelope = <String, dynamic>{...payload, 'id': id, 'requires_ack': true};
    final message = _PendingMessage(id: id, envelope: envelope, send: send);
    _pending[id] = message;
    send(envelope);
    _scheduleRetry(message);
    return id;
  }

  /// Clears the pending entry matching [id] (server echoed `type: ack`).
  ///
  /// A successful delivery is the signal that the link recovered, so a
  /// cleared queue also lifts the degraded flag.
  void ack(String id) {
    final message = _pending.remove(id);
    if (message == null) return;
    message.timer?.cancel();
    debugPrint('[AckOutbox] acked $id');
    if (_pending.isEmpty) isDegraded.value = false;
  }

  /// Drops every pending message of the given `type` without retrying.
  ///
  /// Used for acknowledgements that carry no id — e.g. the server replies
  /// `interrupt_ack` (no id) on the chat channel, which acknowledges every
  /// in-flight interrupt at once.
  void clearByType(String type) {
    final removed = <_PendingMessage>[];
    _pending.removeWhere((_, m) {
      if (m.envelope['type'] == type) {
        removed.add(m);
        return true;
      }
      return false;
    });
    for (final m in removed) {
      m.timer?.cancel();
      debugPrint('[AckOutbox] cleared ${m.id} (type=$type)');
    }
    if (_pending.isEmpty) isDegraded.value = false;
  }

  /// Immediately re-sends all pending messages and resets their retry
  /// budgets. Call when the WebSocket reconnects so nothing queued while
  /// offline is lost.
  void flush() {
    if (_pending.isEmpty) return;
    debugPrint('[AckOutbox] flushing ${_pending.length} pending message(s)');
    for (final m in _pending.values.toList()) {
      m.attempts = 0;
      m.send(m.envelope);
      _scheduleRetry(m);
    }
  }

  void _scheduleRetry(_PendingMessage message) {
    if (_disposed) return;
    message.timer?.cancel();
    message.timer = null;

    if (message.attempts >= maxRetries) {
      _drop(message);
      return;
    }

    final delay = retryBase * (1 << message.attempts);
    message.timer = Timer(delay, () {
      message.timer = null;
      if (_disposed || !_pending.containsKey(message.id)) return;

      message.attempts++;
      message.send(message.envelope);
      _scheduleRetry(message);
    });
  }

  void _drop(_PendingMessage message) {
    if (_pending.remove(message.id) == null) return;
    debugPrint('[AckOutbox] DROPPED ${message.id} after $maxRetries failed attempts');
    isDegraded.value = true;
  }

  String _nextId() {
    final millis = DateTime.now().millisecondsSinceEpoch.toRadixString(16);
    return 'm${millis}_${_seq++}';
  }

  void dispose() {
    _disposed = true;
    for (final m in _pending.values) {
      m.timer?.cancel();
    }
    _pending.clear();
    isDegraded.dispose();
  }
}

class _PendingMessage {
  _PendingMessage({
    required this.id,
    required this.envelope,
    required this.send,
  });

  final String id;
  final Map<String, dynamic> envelope;
  final void Function(Map<String, dynamic> envelope) send;
  int attempts = 0;
  Timer? timer;
}

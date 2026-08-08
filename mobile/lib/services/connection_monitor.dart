import 'dart:async';
import 'package:flutter/foundation.dart';
import '../services/websocket_service.dart';

/// Connection quality level exposed to the UI.
enum ConnectionQuality { excellent, good, degraded, offline }

/// Monitors the control WebSocket channel's health via two independent signals:
///
///   1. **Ping/Pong** — sends a ping every [_pingInterval] on the control channel
///      and waits for a `pong` reply. Server echoes pongs immediately.
///
///   2. **Analytics heartbeat** — every analytics payload received from
///      /ws/mobile/analytics counts as proof the backend is alive. If pings
///      temporarily fail but analytics data keeps arriving, quality stays GOOD
///      instead of flipping to OFFLINE.
///
/// This dual-source design eliminates false offline flickers on LAN.
class ConnectionMonitor {
  static final ConnectionMonitor instance = ConnectionMonitor._internal();
  ConnectionMonitor._internal();

  static const Duration _pingInterval      = Duration(seconds: 8);
  static const Duration _pingTimeout       = Duration(seconds: 5);
  static const int      _missThreshold     = 5;   // consecutive misses → offline
  // Max age of last analytics frame before we stop treating it as alive
  static const Duration _analyticsMaxAge   = Duration(seconds: 15);

  // ── Public state ─────────────────────────────────────────────────────────
  final ValueNotifier<ConnectionQuality> quality =
      ValueNotifier<ConnectionQuality>(ConnectionQuality.offline);

  final ValueNotifier<int> latencyMs = ValueNotifier<int>(0);

  // ── Private ───────────────────────────────────────────────────────────────
  Timer? _pingTimer;
  DateTime? _lastPingAt;
  DateTime? _lastAnalyticsAt;   // timestamp of most recent analytics frame
  int _missedPings = 0;

  StreamSubscription<Map<String, dynamic>>? _controlSub;
  StreamSubscription<Map<String, dynamic>>? _analyticsSub;

  // ── Start / Stop ──────────────────────────────────────────────────────────
  void start() {
    _stop();

    // 1. Listen for pong on control stream
    _controlSub = WebSocketService.instance.messagesStream.listen((data) {
      if (data['type'] == 'pong') _onPong();
    });

    // 2. Treat every analytics frame as a heartbeat
    _analyticsSub = WebSocketService.instance.analyticsStream.listen((data) {
      _lastAnalyticsAt = DateTime.now();
      // If we were degraded/offline but analytics is flowing, recover to good
      if (quality.value == ConnectionQuality.offline ||
          quality.value == ConnectionQuality.degraded) {
        _missedPings = 0;
        quality.value = ConnectionQuality.good;
        debugPrint('[Monitor] Recovered via analytics heartbeat');
      }
    });

    _pingTimer = Timer.periodic(_pingInterval, (_) => _sendPing());
    debugPrint('[Monitor] Connection monitor started (dual-source)');
  }

  void _stop() {
    _pingTimer?.cancel();
    _controlSub?.cancel();
    _analyticsSub?.cancel();
    _pingTimer = null;
    _controlSub = null;
    _analyticsSub = null;
  }

  void dispose() {
    _stop();
    quality.dispose();
    latencyMs.dispose();
  }

  // ── Ping/Pong ─────────────────────────────────────────────────────────────
  void _sendPing() {
    if (!WebSocketService.instance.isConnected.value) {
      _maybeEscalate();
      return;
    }

    _lastPingAt = DateTime.now();
    WebSocketService.instance.sendPing();

    Future.delayed(_pingTimeout, () {
      if (_lastPingAt != null &&
          DateTime.now().difference(_lastPingAt!) >= _pingTimeout) {
        // Ping timed out — but check analytics heartbeat before escalating
        _missedPings++;
        debugPrint('[Monitor] Ping timeout #$_missedPings');
        _maybeEscalate();
      }
    });
  }

  void _onPong() {
    if (_lastPingAt == null) return;
    final rtt = DateTime.now().difference(_lastPingAt!).inMilliseconds;
    latencyMs.value = rtt;
    _lastPingAt = null;
    _missedPings = 0;

    quality.value = rtt < 80
        ? ConnectionQuality.excellent
        : rtt < 250
            ? ConnectionQuality.good
            : ConnectionQuality.degraded;
  }

  /// Only flip to degraded/offline if BOTH ping AND analytics heartbeat are stale.
  void _maybeEscalate() {
    final analyticsAlive = _lastAnalyticsAt != null &&
        DateTime.now().difference(_lastAnalyticsAt!) < _analyticsMaxAge;

    if (analyticsAlive) {
      // Analytics stream is fresh — backend is alive, just pings are slow
      debugPrint('[Monitor] Ping miss ignored — analytics heartbeat active');
      quality.value = ConnectionQuality.good;
      return;
    }

    if (_missedPings >= _missThreshold) {
      quality.value = ConnectionQuality.offline;
      latencyMs.value = 0;
      debugPrint('[Monitor] Both signals lost — marking OFFLINE');
    } else {
      quality.value = ConnectionQuality.degraded;
    }
  }
}

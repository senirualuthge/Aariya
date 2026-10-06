import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Resolved backend address used by the app's WebSocket + WebRTC services.
///
/// Priority:
///  1. Persisted value (user-set in the settings sheet) — `shared_preferences`
///  2. `--dart-define=SERVER_HOST=...` / `SERVER_PORT=...`
///  3. Default `127.0.0.1:8000` (loopback — on a phone that is the
///     phone itself, so LAN use needs the server machine's real IP
///     via dart-define or the settings sheet)
class ServerConfig extends ChangeNotifier {
  static final ServerConfig instance = ServerConfig._internal();
  ServerConfig._internal();

  static const String _kHostKey = 'server_host';
  static const String _kPortKey = 'server_port';
  static const String _kClientIdKey = 'client_id';

  static const String _defaultHost = String.fromEnvironment(
    'SERVER_HOST',
    defaultValue: '127.0.0.1',
  );
  static const int _defaultPort = int.fromEnvironment(
    'SERVER_PORT',
    defaultValue: 8000,
  );

  String _host = _defaultHost;
  int _port = _defaultPort;
  bool _loaded = false;
  String _clientId = '';

  /// Base URL like `192.168.1.57:8000` (no scheme).
  String get host => _host;
  int get port => _port;
  bool get loaded => _loaded;

  /// Stable per-install id for this phone, shared by the chat, control and
  /// analytics channels so the backend counts ONE device instead of one per
  /// channel. Persisted on first [load]; generated in-memory before that so
  /// the id is never empty.
  String get clientId {
    if (_clientId.isEmpty) _clientId = _newClientId();
    return _clientId;
  }

  /// `ws://host:port`
  String get wsBase => 'ws://$_host:$_port';

  /// `http://host:port`
  String get httpBase => 'http://$_host:$_port';

  static String _newClientId() {
    final rng = Random.secure();
    return List<int>.generate(12, (_) => rng.nextInt(256))
        .map((b) => b.toRadixString(16).padLeft(2, '0'))
        .join();
  }

  /// Loads the persisted values once. Safe to call repeatedly.
  Future<void> load() async {
    if (_loaded) return;
    try {
      final prefs = await SharedPreferences.getInstance();
      final host = prefs.getString(_kHostKey);
      final port = prefs.getInt(_kPortKey);
      if (host != null && host.trim().isNotEmpty) _host = host.trim();
      if (port != null && port > 0) _port = port;

      final storedId = prefs.getString(_kClientIdKey);
      if (storedId != null && storedId.trim().isNotEmpty) {
        _clientId = storedId.trim();
      } else {
        // First launch of this install. Persist the id already in memory (the
        // getter mints one on demand) rather than a fresh one — minting a
        // second id here would orphan any channel that connected before
        // bootstrap finished, and the phone would count as two devices.
        await prefs.setString(_kClientIdKey, clientId);
      }
    } catch (e) {
      debugPrint('[ServerConfig] load failed: $e');
    }
    _loaded = true;
    notifyListeners();
  }

  /// Persists a new address and notifies listeners.
  ///
  /// Returns `true` on success. Callers should [WebSocketService.connect]
  /// afterwards to point existing channels at the new host.
  Future<bool> save(String host, int port) async {
    final h = host.trim();
    if (h.isEmpty) return false;
    if (port <= 0 || port > 65535) return false;

    final changed = h != _host || port != _port;
    _host = h;
    _port = port;
    _loaded = true;

    try {
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString(_kHostKey, h);
      await prefs.setInt(_kPortKey, port);
    } catch (e) {
      debugPrint('[ServerConfig] save failed: $e');
      return false;
    }

    if (changed) notifyListeners();
    return true;
  }
}

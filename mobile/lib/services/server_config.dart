import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// Resolved backend address used by the app's WebSocket + WebRTC services.
///
/// Priority:
///  1. Persisted value (user-set in the settings sheet) — `shared_preferences`
///  2. `--dart-define=SERVER_HOST=...` / `SERVER_PORT=...`
///  3. LAN default `192.168.1.57:8000`
class ServerConfig extends ChangeNotifier {
  static final ServerConfig instance = ServerConfig._internal();
  ServerConfig._internal();

  static const String _kHostKey = 'server_host';
  static const String _kPortKey = 'server_port';

  static const String _defaultHost = String.fromEnvironment(
    'SERVER_HOST',
    defaultValue: '192.168.1.57',
  );
  static const int _defaultPort = int.fromEnvironment(
    'SERVER_PORT',
    defaultValue: 8000,
  );

  String _host = _defaultHost;
  int _port = _defaultPort;
  bool _loaded = false;

  /// Base URL like `192.168.1.57:8000` (no scheme).
  String get host => _host;
  int get port => _port;
  bool get loaded => _loaded;

  /// `ws://host:port`
  String get wsBase => 'ws://$_host:$_port';

  /// `http://host:port`
  String get httpBase => 'http://$_host:$_port';

  /// Loads the persisted values once. Safe to call repeatedly.
  Future<void> load() async {
    if (_loaded) return;
    try {
      final prefs = await SharedPreferences.getInstance();
      final host = prefs.getString(_kHostKey);
      final port = prefs.getInt(_kPortKey);
      if (host != null && host.trim().isNotEmpty) _host = host.trim();
      if (port != null && port > 0) _port = port;
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

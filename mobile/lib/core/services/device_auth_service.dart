import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

import 'server_config.dart';

/// One authenticated personal device.
class DeviceIdentity {
  const DeviceIdentity({
    required this.deviceId,
    required this.ownerId,
    required this.role,
    required this.label,
  });

  final String deviceId;
  final String ownerId;
  final String role;
  final String label;

  factory DeviceIdentity.fromJson(Map<String, dynamic> json) => DeviceIdentity(
        deviceId: json['device_id'] as String? ?? '',
        ownerId: json['owner_id'] as String? ?? '',
        role: json['role'] as String? ?? '',
        label: json['label'] as String? ?? '',
      );
}

/// A device-auth failure. [needsPairing] is true when the stored credential is
/// missing, invalid or revoked — reconnecting will not fix it; the user must
/// pair again.
class DeviceAuthException implements Exception {
  const DeviceAuthException(this.message, {this.needsPairing = false});

  final String message;
  final bool needsPairing;

  @override
  String toString() => 'DeviceAuthException: $message';
}

/// Secure, per-device authentication for the phone (Patch 2/3).
///
/// The long-lived credential lives in Android Keystore / iOS Keychain through
/// `flutter_secure_storage`, never in `shared_preferences`. WebSockets use
/// one-use, path-bound tickets offered as the `aariya-ticket.<token>`
/// subprotocol, so the credential is never placed in a connection URL.
class DeviceAuthService {
  static final DeviceAuthService instance = DeviceAuthService._();
  DeviceAuthService._();

  static const String _credentialKey = 'aariya.device.credential';
  static const Duration _timeout = Duration(seconds: 10);

  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  String? _cachedCredential;
  bool _loaded = false;

  /// Flips to true when the server rejects the credential (revoked device).
  /// The UI should show "pair this phone" rather than an endless reconnect.
  final ValueNotifier<bool> needsPairing = ValueNotifier<bool>(false);

  Future<String?> _credential() async {
    if (_loaded) return _cachedCredential;
    try {
      _cachedCredential = await _storage.read(key: _credentialKey);
    } catch (e) {
      debugPrint('[DeviceAuth] secure storage read failed: $e');
      _cachedCredential = null;
    }
    _loaded = true;
    return _cachedCredential;
  }

  Future<bool> get isPaired async => (await _credential()) != null;

  /// Redeem a one-time pairing code created by the local server CLI.
  Future<DeviceIdentity> pair({
    required String pairingCode,
    String label = 'this phone',
    String? platform,
  }) async {
    final resolvedPlatform = platform ??
        (defaultTargetPlatform == TargetPlatform.iOS
            ? 'ios'
            : defaultTargetPlatform == TargetPlatform.android
                ? 'android'
                : 'desktop');
    final response = await _post(
      '/api/auth/device/enroll',
      body: {
        'pairing_code': pairingCode.trim(),
        'label': label.trim().isEmpty ? 'this phone' : label.trim(),
        'platform': resolvedPlatform,
      },
      credential: null,
    );

    if (response.statusCode != 200) {
      throw DeviceAuthException(
        _detail(response) ?? 'Pairing failed',
        needsPairing: true,
      );
    }

    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final credential = body['credential'] as String?;
    if (credential == null || credential.isEmpty) {
      throw const DeviceAuthException('Server did not return a credential');
    }

    await _storage.write(key: _credentialKey, value: credential);
    _cachedCredential = credential;
    _loaded = true;
    needsPairing.value = false;
    return DeviceIdentity.fromJson(body);
  }

  /// The server revoked this device: clear the credential and require pairing.
  Future<void> handleRevocation() async {
    await clear();
    needsPairing.value = true;
  }

  /// Forget the local credential (device revoked, or the user chose to unpair).
  Future<void> clear() async {
    _cachedCredential = null;
    _loaded = true;
    try {
      await _storage.delete(key: _credentialKey);
    } catch (e) {
      debugPrint('[DeviceAuth] secure storage delete failed: $e');
    }
    needsPairing.value = false;
  }

  /// Identity of the paired device, or null when no credential is stored.
  Future<DeviceIdentity?> me() async {
    final credential = await _credential();
    if (credential == null) return null;

    final response = await _get('/api/auth/me', credential: credential);
    if (response.statusCode == 401) {
      await _rejectCredential();
      return null;
    }
    if (response.statusCode != 200) {
      throw DeviceAuthException('Could not read device identity (${response.statusCode})');
    }
    return DeviceIdentity.fromJson(
      jsonDecode(response.body) as Map<String, dynamic>,
    );
  }

  /// Ask the server whether it requires device authentication.
  ///
  /// The response deliberately exposes only the mode: no owner, device list or
  /// pairing information.
  Future<bool> deviceAuthEnabledOnServer() async {
    final response = await http
        .get(
          Uri.parse(
            '${ServerConfig.instance.httpBase}/api/auth/mode',
          ),
        )
        .timeout(_timeout);

    if (response.statusCode != 200) {
      throw DeviceAuthException(
        'Could not verify server authentication mode '
        '(${response.statusCode}).',
      );
    }

    final body =
        jsonDecode(response.body) as Map<String, dynamic>;

    final enabled = body['device_auth_enabled'];

    if (enabled is! bool) {
      throw const DeviceAuthException(
        'Invalid authentication-mode response.',
      );
    }

    return enabled;
  }

  /// Request a single-use ticket for one WebSocket path.
  ///
  /// Returns null when the phone is not paired, so an existing (legacy) server
  /// keeps working during migration. Throws [DeviceAuthException] with
  /// `needsPairing: true` when the credential was revoked, or when the server
  /// requires device auth and this phone has not been paired.
  Future<String?> createWebSocketTicket(String path) async {
    final credential = await _credential();

    if (credential == null) {
      final strictMode = await deviceAuthEnabledOnServer();

      if (strictMode) {
        needsPairing.value = true;

        throw const DeviceAuthException(
          'Pair this phone before connecting to Aariya.',
          needsPairing: true,
        );
      }

      return null;
    }

    final response = await _post(
      '/api/auth/ws-ticket',
      body: {'path': path},
      credential: credential,
    );

    if (response.statusCode == 401) {
      await _rejectCredential();
      throw const DeviceAuthException(
        'This device is no longer trusted. Pair it again.',
        needsPairing: true,
      );
    }
    if (response.statusCode != 200) {
      throw DeviceAuthException(_detail(response) ?? 'Ticket request failed');
    }

    final body = jsonDecode(response.body) as Map<String, dynamic>;
    final ticket = body['ticket'] as String?;
    if (ticket == null || ticket.isEmpty) {
      throw const DeviceAuthException('Server returned an empty ticket');
    }
    return ticket;
  }

  /// Open a WebSocket with a fresh ticket. Falls back to an unauthenticated
  /// connection only when this phone has not been paired yet.
  Future<WebSocketChannel> openAuthenticatedChannel(Uri uri, String path) async {
    final ticket = await createWebSocketTicket(path);
    if (ticket == null) return WebSocketChannel.connect(uri);
    return WebSocketChannel.connect(
      uri,
      protocols: ['aariya.v1', 'aariya-ticket.$ticket'],
    );
  }

  Future<void> _rejectCredential() async {
    await clear();
    needsPairing.value = true;
  }

  Future<http.Response> _post(
    String path, {
    required Map<String, dynamic> body,
    required String? credential,
  }) async {
    return http
        .post(
          Uri.parse('${ServerConfig.instance.httpBase}$path'),
          headers: {
            'Content-Type': 'application/json',
            if (credential != null) 'Authorization': 'Bearer $credential',
          },
          body: jsonEncode(body),
        )
        .timeout(_timeout);
  }

  Future<http.Response> _get(
    String path, {
    required String credential,
  }) async {
    return http.get(
      Uri.parse('${ServerConfig.instance.httpBase}$path'),
      headers: {'Authorization': 'Bearer $credential'},
    ).timeout(_timeout);
  }

  String? _detail(http.Response response) {
    try {
      final body = jsonDecode(response.body);
      if (body is Map && body['detail'] is String) return body['detail'] as String;
    } catch (_) {
      // Non-JSON error body.
    }
    return null;
  }
}

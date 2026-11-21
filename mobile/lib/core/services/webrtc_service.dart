import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;

import 'package:connectivity_plus/connectivity_plus.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:http/http.dart' as http;

import 'device_auth_service.dart';
import 'server_config.dart';

class WebRTCService {
  static final WebRTCService instance = WebRTCService._internal();

  WebRTCService._internal();

  RTCPeerConnection? pc;
  MediaStream? localStream;

  final RTCVideoRenderer audioRenderer = RTCVideoRenderer();

  final ValueNotifier<String> connectionState =
      ValueNotifier<String>('disconnected');

  bool _isInit = false;
  bool _starting = false;
  bool _recovering = false;
  bool _intentionalClose = false;

  int _reconnectAttempts = 0;
  int _lifecycleGeneration = 0;

  String? _lastServerIp;
  String? sessionId;
  StreamSubscription<List<ConnectivityResult>>? _connectivitySubscription;

  static const int _maxReconnectAttempts = 5;
  static const Duration _requestTimeout = Duration(seconds: 20);
  static const Duration _iceGatheringTimeout = Duration(seconds: 15);
  static const Duration _disconnectGracePeriod =
      Duration(seconds: 4);

  Future<void> init() async {
    if (_isInit) return;

    await audioRenderer.initialize();
    _connectivitySubscription = Connectivity().onConnectivityChanged.listen((results) {
      if (_intentionalClose || _recovering) return;
      if (results.isNotEmpty && results.first != ConnectivityResult.none) {
        if (pc == null || connectionState.value == 'failed' || connectionState.value == 'disconnected') {
          unawaited(_recoverConnection());
        }
      }
    });
    _isInit = true;
  }

  Uri _serverUri(String host, String path) {
    final config = ServerConfig.instance;
    final normalizedHost = host.toLowerCase();

    final isLoopback = normalizedHost == 'localhost' ||
        normalizedHost == '127.0.0.1' ||
        normalizedHost == '::1';

    if (!config.secure && !isLoopback) {
      throw StateError(
        'Remote WebRTC connections require HTTPS. '
        'Enable TLS in Aariya connection settings.',
      );
    }

    return Uri.parse('${config.httpBase}$path')
        .replace(host: host, port: config.port);
  }

  Future<void> start([String? serverIp]) async {
    _lastServerIp = serverIp ?? ServerConfig.instance.host;
    if (!_recovering) {
      _intentionalClose = false;
      _reconnectAttempts = 0;
      _lifecycleGeneration++;
    }

    await _startInternal(_lifecycleGeneration);
  }

  Future<void> _startInternal(int generation) async {
    if (_starting) {
      throw StateError('A WebRTC connection attempt is already running.');
    }

    _starting = true;
    connectionState.value = 'connecting';

    try {
      final host = _lastServerIp ?? ServerConfig.instance.host;

      // Validate host / TLS before acquiring any hardware or credentials.
      _serverUri(host, '/offer');

      // Check device credentials before initializing mic or renderer;
      // this lets tests assert on auth failures without native plugin calls.
      final headers =
          await DeviceAuthService.instance.authenticatedHeaders();

      await _cleanupConnection();
      await init();

      if (_intentionalClose || generation != _lifecycleGeneration) {
        return;
      }

      // Obtain a fresh, authenticated, short-lived TURN credential
      // for every newly negotiated peer connection.
      final iceServers = await _fetchIceServers(host, headers);

      if (_intentionalClose || generation != _lifecycleGeneration) {
        return;
      }

      final peer = await createPeerConnection({
        'iceServers': iceServers,
        'sdpSemantics': 'unified-plan',
      });

      pc = peer;

      peer.onConnectionState = (state) {
        if (!identical(pc, peer)) return;

        final value = state.toString().split('.').last;
        connectionState.value = value;

        debugPrint('[WebRTC] Peer state: $value');

        if (state ==
            RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
          _reconnectAttempts = 0;
          return;
        }

        if (state ==
            RTCPeerConnectionState.RTCPeerConnectionStateFailed) {
          _scheduleRecovery(peer);
          return;
        }

        if (state ==
            RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
          _checkDisconnectedPeer(peer);
        }
      };

      peer.onIceConnectionState = (state) {
        debugPrint('[WebRTC] ICE state: $state');

        if (state == RTCIceConnectionState.RTCIceConnectionStateFailed) {
          _scheduleRecovery(peer);
        }
      };

      peer.onIceGatheringState = (state) {
        debugPrint('[WebRTC] ICE gathering: $state');
      };

      peer.onTrack = (event) {
        if (event.track.kind == 'audio' && event.streams.isNotEmpty) {
          audioRenderer.srcObject = event.streams.first;
        }
      };

      localStream = await navigator.mediaDevices.getUserMedia({
        'audio': {
          'echoCancellation': true,
          'noiseSuppression': true,
          'autoGainControl': true,
        },
        'video': false,
      });

      final stream = localStream!;

      for (final track in stream.getAudioTracks()) {
        await peer.addTrack(track, stream);
      }

      final offer = await peer.createOffer({
        'offerToReceiveAudio': true,
        'offerToReceiveVideo': false,
      });

      await peer.setLocalDescription(offer);
      await _waitForIceGathering(peer);

      if (_intentionalClose || generation != _lifecycleGeneration) {
        return;
      }

      final localDescription = await peer.getLocalDescription();

      if (localDescription == null ||
          localDescription.sdp == null ||
          localDescription.sdp!.isEmpty) {
        throw StateError('WebRTC did not produce a local SDP offer.');
      }

      final response = await http
          .post(
            _serverUri(host, '/offer'),
            headers: headers,
            body: jsonEncode({
              'sdp': localDescription.sdp,
              'type': localDescription.type,
            }),
          )
          .timeout(_requestTimeout);

      if (response.statusCode == 401 || response.statusCode == 403) {
        await DeviceAuthService.instance.handleUnauthorizedResponse();

        throw const DeviceAuthException(
          'This device is no longer authorized. Pair it again.',
          needsPairing: true,
        );
      }

      if (response.statusCode != 200) {
        throw StateError(
          'WebRTC negotiation failed '
          '(${response.statusCode}): ${response.body}',
        );
      }

      final decoded = jsonDecode(response.body);

      if (decoded is! Map<String, dynamic>) {
        throw const FormatException(
          'Invalid WebRTC answer from the server.',
        );
      }

      final answerSdp = decoded['sdp'];
      final answerType = decoded['type'];
      final returnedSessionId = decoded['session_id'];

      if (answerSdp is! String ||
          answerSdp.isEmpty ||
          answerType is! String ||
          answerType.isEmpty) {
        throw const FormatException(
          'The server returned an incomplete WebRTC answer.',
        );
      }

      if (returnedSessionId is! String || returnedSessionId.isEmpty) {
        throw const FormatException(
          'The server did not return a valid WebRTC session ID.',
        );
      }
      sessionId = returnedSessionId;

      if (_intentionalClose || generation != _lifecycleGeneration) {
        return;
      }

      await peer.setRemoteDescription(
        RTCSessionDescription(answerSdp, answerType),
      );

      connectionState.value = 'negotiating';
    } catch (error, stackTrace) {
      debugPrint('[WebRTC] Start failed: $error');
      debugPrintStack(stackTrace: stackTrace);

      await _cleanupConnection();

      if (!_intentionalClose &&
          generation == _lifecycleGeneration) {
        connectionState.value = 'failed';
      }

      rethrow;
    } finally {
      _starting = false;
    }
  }

  Future<List<Map<String, dynamic>>> _fetchIceServers(
    String host,
    Map<String, String> headers,
  ) async {
    final response = await http
        .get(
          _serverUri(host, '/api/webrtc/turn-credentials'),
          headers: headers,
        )
        .timeout(_requestTimeout);

    if (response.statusCode == 401 || response.statusCode == 403) {
      await DeviceAuthService.instance.handleUnauthorizedResponse();

      throw const DeviceAuthException(
        'TURN credential request rejected. Pair this device again.',
        needsPairing: true,
      );
    }

    if (response.statusCode != 200) {
      throw StateError(
        'Could not obtain TURN credentials '
        '(${response.statusCode}): ${response.body}',
      );
    }

    final decoded = jsonDecode(response.body);

    if (decoded is! Map<String, dynamic>) {
      throw const FormatException('Invalid TURN credential response.');
    }

    final urls = decoded['urls'];
    final username = decoded['username'];
    final credential = decoded['credential'];
    final ttl = decoded['ttl'];

    if (urls is! List ||
        urls.isEmpty ||
        urls.any((url) => url is! String || url.isEmpty) ||
        username is! String ||
        username.isEmpty ||
        credential is! String ||
        credential.isEmpty ||
        ttl is! int ||
        ttl <= 0) {
      throw const FormatException(
        'TURN credentials are incomplete or invalid.',
      );
    }

    debugPrint('[WebRTC] Received temporary TURN credentials '
        '(TTL: $ttl seconds).');

    return [
      {
        'urls': urls.cast<String>(),
        'username': username,
        'credential': credential,
      },
      {
        'urls': 'stun:stun.l.google.com:19302',
      },
    ];
  }

  Future<void> _checkDisconnectedPeer(
    RTCPeerConnection peer,
  ) async {
    await Future.delayed(_disconnectGracePeriod);

    if (_intentionalClose || !identical(pc, peer)) return;

    final state = await peer.getConnectionState();

    if (state ==
            RTCPeerConnectionState.RTCPeerConnectionStateDisconnected ||
        state == RTCPeerConnectionState.RTCPeerConnectionStateFailed) {
      _scheduleRecovery(peer);
    }
  }

  void _scheduleRecovery(RTCPeerConnection peer) {
    if (_intentionalClose ||
        _recovering ||
        !identical(pc, peer)) {
      return;
    }

    unawaited(_recoverConnection());
  }

  Future<void> _recoverConnection() async {
    if (_recovering || _intentionalClose) return;

    _recovering = true;
    final generation = _lifecycleGeneration;

    try {
      while (_reconnectAttempts < _maxReconnectAttempts &&
          !_intentionalClose &&
          generation == _lifecycleGeneration) {
        _reconnectAttempts++;

        final seconds = 1 << (_reconnectAttempts - 1);
        final jitterMs = math.Random().nextInt(500);

        connectionState.value = 'reconnecting';

        debugPrint(
          '[WebRTC] Recovery attempt '
          '$_reconnectAttempts/$_maxReconnectAttempts',
        );

        await Future.delayed(
          Duration(seconds: seconds, milliseconds: jitterMs),
        );

        if (_intentionalClose ||
            generation != _lifecycleGeneration) {
          return;
        }

        try {
          await _startInternal(generation);

          if (connectionState.value == 'negotiating' ||
              connectionState.value == 'connected') {
            _reconnectAttempts = 0;
            return;
          }
        } on DeviceAuthException catch (error) {
          if (error.needsPairing) {
            connectionState.value = 'authentication_required';
            return;
          }
          debugPrint('[WebRTC] Authentication error: $error');
        } catch (error) {
          debugPrint('[WebRTC] Recovery attempt failed: $error');
        }
      }

      if (!_intentionalClose &&
          generation == _lifecycleGeneration) {
        connectionState.value = 'failed';
      }
    } finally {
      _recovering = false;
    }
  }

  Future<void> _waitForIceGathering(
    RTCPeerConnection peer,
  ) async {
    final currentState = await peer.getIceGatheringState();

    if (currentState ==
        RTCIceGatheringState.RTCIceGatheringStateComplete) {
      return;
    }

    final completer = Completer<void>();

    peer.onIceGatheringState = (state) {
      if (state ==
              RTCIceGatheringState.RTCIceGatheringStateComplete &&
          !completer.isCompleted) {
        completer.complete();
      }
    };

    final updatedState = await peer.getIceGatheringState();

    if (updatedState ==
            RTCIceGatheringState.RTCIceGatheringStateComplete &&
        !completer.isCompleted) {
      completer.complete();
    }

    await completer.future.timeout(_iceGatheringTimeout);
  }

  Future<void> stop() async {
    _intentionalClose = true;
    _lifecycleGeneration++;
    _reconnectAttempts = 0;

    await _cleanupConnection();
    connectionState.value = 'disconnected';
  }

  Future<void> _cleanupConnection() async {
    sessionId = null;
    final stream = localStream;
    localStream = null;

    if (stream != null) {
      for (final track in stream.getTracks()) {
        try {
          await track.stop();
        } catch (error) {
          debugPrint('[WebRTC] Track stop failed: $error');
        }
      }

      try {
        await stream.dispose();
      } catch (error) {
        debugPrint('[WebRTC] Stream disposal failed: $error');
      }
    }

    final peer = pc;
    pc = null;

    if (peer != null) {
      try {
        await peer.close();
      } catch (error) {
        debugPrint('[WebRTC] Peer close failed: $error');
      }

      try {
        await peer.dispose();
      } catch (error) {
        debugPrint('[WebRTC] Peer disposal failed: $error');
      }
    }

    if (_isInit) {
      audioRenderer.srcObject = null;
    }
  }

  Future<void> setMicrophoneEnabled(bool enabled) async {
    final stream = localStream;
    if (stream == null) return;
    for (final track in stream.getAudioTracks()) {
      track.enabled = enabled;
    }
  }

  Future<void> interrupt() async {
    final id = sessionId;
    if (id == null || id.isEmpty) return;
    final host = _lastServerIp ?? ServerConfig.instance.host;
    final headers = await DeviceAuthService.instance.authenticatedHeaders();
    final response = await http
        .post(
          _serverUri(host, '/interrupt'),
          headers: headers,
          body: jsonEncode({'session_id': id}),
        )
        .timeout(_requestTimeout);
    if (response.statusCode == 401 || response.statusCode == 403) {
      await DeviceAuthService.instance.handleUnauthorizedResponse();
      throw const DeviceAuthException(
        'Device authorization expired.',
        needsPairing: true,
      );
    }
    if (response.statusCode != 200) {
      throw StateError('WebRTC interruption failed: ${response.statusCode}');
    }
  }

  Future<void> dispose() async {
    await stop();

    await _connectivitySubscription?.cancel();
    _connectivitySubscription = null;

    if (_isInit) {
      await audioRenderer.dispose();
      _isInit = false;
    }

    connectionState.dispose();
  }
}

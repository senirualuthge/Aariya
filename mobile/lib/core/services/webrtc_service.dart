import 'dart:async';
import 'dart:convert';

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

  final ValueNotifier<String> connectionState = ValueNotifier<String>(
    'disconnected',
  );

  bool _isInit = false;
  bool _starting = false;
  String? _lastServerIp;

  static const int _maxReconnectAttempts = 5;
  int _reconnectAttempts = 0;
  bool _recovering = false;
  bool _intentionalClose = false;

  static const Duration _requestTimeout = Duration(seconds: 20);
  static const Duration _iceGatheringTimeout = Duration(seconds: 15);

  Future<void> init() async {
    if (_isInit) return;

    await audioRenderer.initialize();
    _isInit = true;
  }

  Uri _offerUri(String host) {
    final config = ServerConfig.instance;

    final normalizedHost = host.toLowerCase();
    final isLoopback =
        normalizedHost == 'localhost' ||
        normalizedHost == '127.0.0.1' ||
        normalizedHost == '::1';

    if (!config.secure && !isLoopback) {
      throw StateError(
        'Remote WebRTC connections require HTTPS. '
        'Enable TLS in Aariya connection settings.',
      );
    }

    return Uri.parse(
      '${config.httpBase}/offer',
    ).replace(host: host, port: config.port);
  }

  Future<List<Map<String, dynamic>>> _fetchIceServers(String host) async {
    final config = ServerConfig.instance;

    final uri = Uri.parse(
      '${config.httpBase}/api/webrtc/turn-credentials',
    ).replace(host: host, port: config.port);

    final headers = await DeviceAuthService.instance.authenticatedHeaders();

    final response = await http
        .get(uri, headers: headers)
        .timeout(_requestTimeout);

    if (response.statusCode == 401) {
      await DeviceAuthService.instance.handleUnauthorizedResponse();

      throw const DeviceAuthException(
        'Device authorization expired. Pair this device again.',
        needsPairing: true,
      );
    }

    // TURN is optional. STUN-only operation is allowed when
    // the backend explicitly reports that TURN is not configured.
    if (response.statusCode == 503) {
      debugPrint('[WebRTC] TURN unavailable; using STUN');
      return [
        {'urls': 'stun:stun.l.google.com:19302'},
      ];
    }

    if (response.statusCode != 200) {
      throw StateError(
        'TURN credential request failed: ${response.statusCode}',
      );
    }

    final body = jsonDecode(response.body);

    if (body is! Map<String, dynamic>) {
      throw const FormatException('Invalid TURN credential response');
    }

    final urls = body['urls'];
    final username = body['username'];
    final credential = body['credential'];
    final ttl = body['ttl'];

    if (urls is! List ||
        urls.isEmpty ||
        username is! String ||
        username.isEmpty ||
        credential is! String ||
        credential.isEmpty ||
        ttl is! int ||
        ttl <= 0) {
      throw const FormatException('Incomplete TURN credentials');
    }

    return [
      {'urls': 'stun:stun.l.google.com:19302'},
      {
        'urls': urls.cast<String>(),
        'username': username,
        'credential': credential,
      },
    ];
  }

  Future<void> recoverConnection() async {
    if (_recovering || _intentionalClose) return;

    _recovering = true;

    try {
      while (_reconnectAttempts < _maxReconnectAttempts && !_intentionalClose) {
        _reconnectAttempts++;

        final delay = Duration(seconds: 1 << (_reconnectAttempts - 1));

        await Future.delayed(delay);

        if (_intentionalClose) return;

        try {
          await _restartConnection();
          _reconnectAttempts = 0;
          return;
        } catch (error, stackTrace) {
          debugPrint(
            '[WebRTC] Recovery attempt '
            '$_reconnectAttempts failed: $error\n$stackTrace',
          );
        }
      }

      throw StateError(
        'WebRTC recovery failed after '
        '$_maxReconnectAttempts attempts',
      );
    } finally {
      _recovering = false;
    }
  }

  Future<void> _restartConnection() async {
    if (_intentionalClose) return;

    // Must perform a new authenticated offer/answer negotiation.
    // A new peer connection also obtains fresh TURN credentials.
    await stop();

    if (_intentionalClose) return;

    await start(_lastServerIp);
  }

  void handleConnectionFailure() {
    if (_intentionalClose || _recovering) return;

    recoverConnection().catchError((Object error) {
      debugPrint('[WebRTC] Recovery exhausted: $error');
    });
  }

  void resetRecoveryState() {
    _reconnectAttempts = 0;
    _recovering = false;
  }

  void cancelRecovery() {
    _intentionalClose = true;
  }

  void allowConnection() {
    _intentionalClose = false;
    resetRecoveryState();
  }

  Future<void> start([String? serverIp]) async {
    if (_starting) {
      throw StateError('A WebRTC connection attempt is already running.');
    }

    final config = ServerConfig.instance;
    final host = serverIp ?? config.host;
    final offerUri = _offerUri(host);

    // Verify authentication before acquiring local media or hardware
    final headers = await DeviceAuthService.instance.authenticatedHeaders();

    if (pc != null) {
      await stop();
    }

    allowConnection();
    _lastServerIp = serverIp;
    _starting = true;
    connectionState.value = 'connecting';

    try {
      await init();

      final iceServers = await _fetchIceServers(host);

      final peer = await createPeerConnection({
        'iceServers': iceServers,
        'sdpSemantics': 'unified-plan',
      });

      pc = peer;

      peer.onConnectionState = (state) {
        connectionState.value = state.toString().split('.').last;
        debugPrint('[WebRTC] Connection state: $state');

        if (state == RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
          resetRecoveryState();
        }

        if (state == RTCPeerConnectionState.RTCPeerConnectionStateFailed ||
            state ==
                RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
          handleConnectionFailure();
        }
      };

      peer.onIceConnectionState = (state) {
        debugPrint('[WebRTC] ICE state: $state');
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

      final localDescription = await peer.getLocalDescription();

      if (localDescription == null ||
          localDescription.sdp == null ||
          localDescription.sdp!.isEmpty) {
        throw StateError('WebRTC did not produce a local SDP offer.');
      }

      final response = await http
          .post(
            offerUri,
            headers: headers,
            body: jsonEncode({
              'sdp': localDescription.sdp,
              'type': localDescription.type,
            }),
          )
          .timeout(_requestTimeout);

      if (response.statusCode == 401) {
        await DeviceAuthService.instance.handleUnauthorizedResponse();
        throw const DeviceAuthException(
          'The device credential was rejected. Pair this device again.',
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
        throw const FormatException('Invalid WebRTC answer from the server.');
      }

      final answerSdp = decoded['sdp'];
      final answerType = decoded['type'];

      if (answerSdp is! String ||
          answerSdp.isEmpty ||
          answerType is! String ||
          answerType.isEmpty) {
        throw const FormatException(
          'The server returned an incomplete WebRTC answer.',
        );
      }

      await peer.setRemoteDescription(
        RTCSessionDescription(answerSdp, answerType),
      );

      connectionState.value = 'negotiating';
    } catch (error, stackTrace) {
      debugPrint('[WebRTC] Start failed: $error');
      debugPrintStack(stackTrace: stackTrace);

      await _cleanupConnection();
      connectionState.value = 'failed';

      rethrow;
    } finally {
      _starting = false;
    }
  }

  Future<void> _waitForIceGathering(RTCPeerConnection peer) async {
    final currentState = await peer.getIceGatheringState();

    if (currentState == RTCIceGatheringState.RTCIceGatheringStateComplete) {
      return;
    }

    final completer = Completer<void>();

    peer.onIceGatheringState = (state) {
      debugPrint('[WebRTC] ICE gathering state: $state');

      if (state == RTCIceGatheringState.RTCIceGatheringStateComplete &&
          !completer.isCompleted) {
        completer.complete();
      }
    };

    final updatedState = await peer.getIceGatheringState();

    if (updatedState == RTCIceGatheringState.RTCIceGatheringStateComplete &&
        !completer.isCompleted) {
      completer.complete();
    }

    await completer.future.timeout(_iceGatheringTimeout);
  }

  Future<void> stop() async {
    cancelRecovery();
    _starting = false;
    await _cleanupConnection();
    connectionState.value = 'disconnected';
  }

  Future<void> _cleanupConnection() async {
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
      try {
        audioRenderer.srcObject = null;
      } catch (error) {
        debugPrint('[WebRTC] audioRenderer reset failed: $error');
      }
    }
  }

  Future<void> dispose() async {
    await stop();

    if (_isInit) {
      await audioRenderer.dispose();
      _isInit = false;
    }

    connectionState.dispose();
  }
}

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
  bool _isReconnecting = false;
  int _retryCount = 0;
  static const int _maxRetries = 5;
  Timer? _reconnectTimer;
  String? _lastServerIp;

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
    final iceServers = <Map<String, dynamic>>[
      {'urls': 'stun:stun.l.google.com:19302'},
    ];

    try {
      final config = ServerConfig.instance;
      final uri = Uri.parse(
        '${config.httpBase}/api/webrtc/turn-credentials',
      ).replace(host: host, port: config.port);
      final headers = await DeviceAuthService.instance.authenticatedHeaders();
      final response = await http
          .get(uri, headers: headers)
          .timeout(_requestTimeout);

      if (response.statusCode == 200) {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          final urls = decoded['urls'];
          final username = decoded['username'];
          final credential = decoded['credential'];
          if (urls != null && username != null && credential != null) {
            iceServers.add({
              'urls': urls,
              'username': username,
              'credential': credential,
            });
            debugPrint('[WebRTC] Acquired dynamic TURN credentials');
          }
        }
      } else {
        debugPrint(
          '[WebRTC] TURN credentials unavailable (${response.statusCode}), using STUN only.',
        );
      }
    } catch (e) {
      debugPrint(
        '[WebRTC] Could not load TURN credentials: $e. Using STUN only.',
      );
    }

    return iceServers;
  }

  void _handleDisconnect() {
    if (_starting || _isReconnecting) return;
    _scheduleReconnect();
  }

  void _scheduleReconnect() {
    if (_retryCount >= _maxRetries) {
      debugPrint('[WebRTC] Maximum reconnection attempts reached.');
      connectionState.value = 'failed';
      return;
    }

    _reconnectTimer?.cancel();
    final delay = Duration(
      milliseconds: (1000 * (1 << _retryCount)).clamp(1000, 16000),
    );
    _retryCount++;
    debugPrint(
      '[WebRTC] Reconnecting attempt $_retryCount/$_maxRetries in ${delay.inSeconds}s...',
    );

    _reconnectTimer = Timer(delay, () async {
      try {
        await restartIce();
      } on DeviceAuthException catch (e) {
        debugPrint('[WebRTC] Auth revoked during reconnect: $e');
        _retryCount = _maxRetries;
        await stop();
      } catch (e) {
        debugPrint('[WebRTC] Reconnect failed: $e');
        if (connectionState.value != 'connected' &&
            connectionState.value != 'disconnected') {
          _scheduleReconnect();
        }
      }
    });
  }

  Future<void> restartIce() async {
    if (pc == null || localStream == null) {
      await start(_lastServerIp);
      return;
    }

    if (_isReconnecting) return;
    _isReconnecting = true;
    connectionState.value = 'connecting';

    try {
      final config = ServerConfig.instance;
      final host = _lastServerIp ?? config.host;
      final offerUri = _offerUri(host);
      final headers = await DeviceAuthService.instance.authenticatedHeaders();

      final peer = pc!;
      final offer = await peer.createOffer({
        'iceRestart': true,
        'offerToReceiveAudio': true,
        'offerToReceiveVideo': false,
      });

      await peer.setLocalDescription(offer);
      await _waitForIceGathering(peer);

      final localDescription = await peer.getLocalDescription();
      if (localDescription == null ||
          localDescription.sdp == null ||
          localDescription.sdp!.isEmpty) {
        throw StateError('WebRTC did not produce an ICE restart SDP offer.');
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
          'ICE restart negotiation failed (${response.statusCode}): ${response.body}',
        );
      }

      final decoded = jsonDecode(response.body);
      if (decoded is! Map<String, dynamic>) {
        throw const FormatException(
          'Invalid WebRTC answer during ICE restart.',
        );
      }

      final answerSdp = decoded['sdp'];
      final answerType = decoded['type'];
      if (answerSdp is! String || answerType is! String) {
        throw const FormatException(
          'Incomplete WebRTC answer during ICE restart.',
        );
      }

      await peer.setRemoteDescription(
        RTCSessionDescription(answerSdp, answerType),
      );
      connectionState.value = 'negotiating';
    } catch (e) {
      debugPrint('[WebRTC] restartIce failed: $e. Falling back to full start.');
      if (e is DeviceAuthException) rethrow;
      await start(_lastServerIp);
    } finally {
      _isReconnecting = false;
    }
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
        debugPrint('[WebRTC] Peer state: ${connectionState.value}');
        if (state == RTCPeerConnectionState.RTCPeerConnectionStateFailed ||
            state ==
                RTCPeerConnectionState.RTCPeerConnectionStateDisconnected) {
          _handleDisconnect();
        } else if (state ==
            RTCPeerConnectionState.RTCPeerConnectionStateConnected) {
          _retryCount = 0;
          _reconnectTimer?.cancel();
          _reconnectTimer = null;
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
    _starting = false;
    _isReconnecting = false;
    _retryCount = 0;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
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

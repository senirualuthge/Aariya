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

  Future<void> start([String? serverIp]) async {
    if (_starting) {
      throw StateError('A WebRTC connection attempt is already running.');
    }

    if (pc != null) {
      await stop();
    }

    _starting = true;
    connectionState.value = 'connecting';

    try {
      await init();

      final config = ServerConfig.instance;
      final host = serverIp ?? config.host;

      final offerUri = _offerUri(host);

      final headers = await DeviceAuthService.instance.authenticatedHeaders();

      // Do not embed static TURN usernames/passwords in the mobile app.
      // Production TURN credentials must be short-lived and issued by
      // an authenticated backend endpoint.
      final peer = await createPeerConnection({
        'iceServers': [
          {'urls': 'stun:stun.l.google.com:19302'},
        ],
        'sdpSemantics': 'unified-plan',
      });

      pc = peer;

      peer.onConnectionState = (state) {
        connectionState.value = state.toString().split('.').last;
        debugPrint('[WebRTC] Peer state: ${connectionState.value}');
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

    // Check again after installing the listener to avoid missing a
    // completion event between the initial state check and listener setup.
    final updatedState = await peer.getIceGatheringState();

    if (updatedState == RTCIceGatheringState.RTCIceGatheringStateComplete &&
        !completer.isCompleted) {
      completer.complete();
    }

    await completer.future.timeout(_iceGatheringTimeout);
  }

  Future<void> stop() async {
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

    audioRenderer.srcObject = null;
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

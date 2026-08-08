import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:flutter_webrtc/flutter_webrtc.dart';
import 'package:http/http.dart' as http;
import 'server_config.dart';

class WebRTCService {
  static final WebRTCService instance = WebRTCService._internal();

  RTCPeerConnection? pc;
  MediaStream? localStream;
  final RTCVideoRenderer audioRenderer = RTCVideoRenderer();
  bool _isInit = false;

  WebRTCService._internal();

  Future<void> init() async {
    if (_isInit) return;
    await audioRenderer.initialize();
    _isInit = true;
  }

  Future<void> start([String? serverIp]) async {
    if (!_isInit) await init();
    final host = serverIp ?? ServerConfig.instance.host;
    final port = ServerConfig.instance.port;
    pc = await createPeerConnection({
      "iceServers": [
        {"urls": "stun:stun.l.google.com:19302"},
        {
          "urls": "turn:$host:3478",
          "username": "aigirl",
          "credential": "aigirl_voice"
        }
      ]
    });

    // Get microphone
    localStream = await navigator.mediaDevices.getUserMedia({
      "audio": true,
      "video": false,
    });

    // Send audio
    localStream!.getTracks().forEach((track) {
      pc!.addTrack(track, localStream!);
    });

    // Receive audio (placeholder print for now)
    pc!.onTrack = (event) {
      debugPrint("Receiving RTC Track audio: ${event.track.kind}");
      if (event.streams.isNotEmpty) {
        audioRenderer.srcObject = event.streams[0];
      }
    };

    // Create SDP offer
    RTCSessionDescription offer = await pc!.createOffer();
    await pc!.setLocalDescription(offer);

    // Negotiate with the Python backend
    final response = await http.post(
      Uri.parse("http://$host:$port/offer"),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "sdp": offer.sdp,
        "type": offer.type,
      }),
    );

    if (response.statusCode == 200) {
      final data = jsonDecode(response.body);
      RTCSessionDescription answer = RTCSessionDescription(
        data["sdp"],
        data["type"],
      );
      await pc!.setRemoteDescription(answer);
    } else {
      debugPrint("Failed to negotiate WebRTC: ${response.body}");
    }
  }

  Future<void> stop() async {
    localStream?.dispose();
    await pc?.close();
    await pc?.dispose();
    audioRenderer.srcObject = null;
  }
}

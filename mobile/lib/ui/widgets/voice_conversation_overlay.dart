import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:camera/camera.dart';
import 'package:permission_handler/permission_handler.dart';
import '../../core/audio_analyser.dart';
import '../../state/chat_controller.dart';
import '../../services/websocket_service.dart';
import 'voice_reactive_orb.dart';
import 'emotion_ring.dart';
import 'animated_text_stream.dart';
import '../../brain/client_brain.dart';
class VoiceConversationOverlay extends StatefulWidget {
  final ChatController chatController;
  final SpeechToText speechToText;
  final bool startWithCamera;

  const VoiceConversationOverlay({
    super.key,
    required this.chatController,
    required this.speechToText,
    this.startWithCamera = false,
  });

  @override
  State<VoiceConversationOverlay> createState() =>
      _VoiceConversationOverlayState();
}

enum VoiceState { listening, processing, speaking }

class _VoiceConversationOverlayState extends State<VoiceConversationOverlay>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {

  // ─── State ────────────────────────────────────────────────────────────────
  VoiceState _state = VoiceState.listening;
  String _currentText = 'Listening...';
  String _lastSentWords = '';
  
  // Live token streaming buffer
  String _streamBuffer = '';
  bool _isStreamingTokens = false;

  // ─── Flags ─────────────────────────────────────────────────────────────────
  bool _isListening = false;
  bool _isInBackground = false;
  bool _isMicMuted = false;
  bool _isCameraEnabled = false;
  bool _cameraInitialising = false;

  // ─── Controllers ───────────────────────────────────────────────────────────
  CameraController? _cameraController;
  Timer? _restartTimer;
  StreamSubscription<Map<String, dynamic>>? _wsSubscription;

  // Shared app-wide FFT analyser. While the user is LISTENING, speech_to_text
  // owns the mic (ASR cannot share it on mobile), so the orb then uses its
  // level; once the mic is free (processing / speaking) the analyser drives
  // the orb with the same low/mid/high bands as the home screen.
  final AudioAnalyser _analyser = AudioAnalyser.instance;
  StreamSubscription<AudioLevels>? _analyserSub;
  double _analyserLevel = 0;
  double _bandMid = 0, _bandHigh = 0;

  // Live mic level 0..1 — drives the voice-reactive orb while listening.
  double _micLevel = 0;

  // Attention shift — orb moves toward context
  Offset _orbOffset = Offset.zero;

  // ──────────────────────────────────────────────────────────────────────────
  // LIFECYCLE
  // ──────────────────────────────────────────────────────────────────────────

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);

    widget.speechToText.statusListener = _onSpeechStatus;

    widget.chatController.onTtsCompletion = () {
      if (!mounted || _isInBackground) return;
      if (_state == VoiceState.speaking) {
        if (_isMicMuted) {
          setState(() => _state = VoiceState.listening);
        } else {
          _scheduleListenRestart(delay: 300);
        }
      }
    };

    widget.chatController.addListener(_onBrainUpdate);
    _subscribeToTokenStream();
    _analyserSub = _analyser.levels.listen(_onAnalyserLevels);

    if (widget.startWithCamera) _toggleCamera();
    _startListening();
  }

  // ── Live Token Streaming ─────────────────────────────────────────────────
  void _subscribeToTokenStream() {
    _wsSubscription = WebSocketService.instance.messagesStream.listen((data) {
      if (!mounted) return;
      final type = data['type'] as String? ?? '';
      switch (type) {
        case 'thinking':
          setState(() {
            _isStreamingTokens = false;
            _streamBuffer = '';
            _state = VoiceState.processing;
            _currentText = 'Thinking\u2026';
          });
          _shiftAttentionFor(VoiceState.processing);
          break;
        case 'text.stream':
          final chunk = data['chunk'] as String? ?? '';
          if (chunk.isEmpty) break;
          setState(() {
            _isStreamingTokens = true;
            _streamBuffer += chunk;
            _currentText = _streamBuffer;
          });
          break;
        case 'state.update':
        case 'response_end':
          // Token stream done — transition to speaking state
          setState(() => _isStreamingTokens = false);
          break;
        case 'interrupted':
          setState(() {
            _isStreamingTokens = false;
            _streamBuffer = '';
          });
          break;
      }
    });
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _restartTimer?.cancel();
    _wsSubscription?.cancel();
    _analyserSub?.cancel();
    widget.chatController.onTtsCompletion = null;
    widget.chatController.removeListener(_onBrainUpdate);
    widget.speechToText.statusListener = null;
    widget.speechToText.stop();
    unawaited(_stopAnalyser());
    _isListening = false;
    _disposeCamera();
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycle) {
    final backgrounding = lifecycle == AppLifecycleState.paused ||
        lifecycle == AppLifecycleState.inactive ||
        lifecycle == AppLifecycleState.hidden;

    if (backgrounding && !_isInBackground) {
      _isInBackground = true;
      _restartTimer?.cancel();
      widget.speechToText.stop();
      unawaited(_stopAnalyser());
      _isListening = false;
      widget.chatController.stopSpeaking();
      _cameraController?.pausePreview();
    } else if (lifecycle == AppLifecycleState.resumed && _isInBackground) {
      _isInBackground = false;
      _resumeCamera();
      _scheduleListenRestart(delay: 600);
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // ATTENTION SHIFT helpers
  // ──────────────────────────────────────────────────────────────────────────

  void _shiftAttentionFor(VoiceState state) {
    final offset = switch (state) {
      VoiceState.listening  => const Offset(0, 40),   // drift toward mic
      VoiceState.speaking   => const Offset(0, -24),  // drift toward text
      VoiceState.processing => Offset.zero,
    };
    if (_orbOffset != offset) setState(() => _orbOffset = offset);
  }

  // ──────────────────────────────────────────────────────────────────────────
  // BRAIN STATE LISTENER
  // ──────────────────────────────────────────────────────────────────────────

  void _onBrainUpdate() {
    if (!mounted) return;
    final brain = widget.chatController.brain;

    if (brain.isSpeaking && _state != VoiceState.speaking) {
      setState(() {
        _state = VoiceState.speaking;
        _currentText = brain.responseText.isNotEmpty
            ? brain.responseText
            : _currentText;
      });
      _shiftAttentionFor(VoiceState.speaking);
      // Mic is free while Aariya speaks → let the analyser drive the orb.
      unawaited(_ensureAnalyser());
    } else if (brain.isListening && _state != VoiceState.listening) {
      setState(() => _state = VoiceState.listening);
      _shiftAttentionFor(VoiceState.listening);
      _scheduleListenRestart(delay: 200);
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // SPEECH
  // ──────────────────────────────────────────────────────────────────────────

  void _onSpeechStatus(String status) {
    if (!mounted || _isMicMuted || _isInBackground) return;

    if (status == 'done' || status == 'notListening') {
      _isListening = false;
      if (_state != VoiceState.listening) return;

      final text = _currentText.trim();
      if (text.isNotEmpty && text != 'Listening...') {
        _processUserSpeech(text);
      } else {
        _scheduleListenRestart(delay: 400);
      }
    }
  }

  void _scheduleListenRestart({int delay = 300}) {
    _restartTimer?.cancel();
    _restartTimer = Timer(Duration(milliseconds: delay), () {
      if (mounted && !_isInBackground && !_isMicMuted && !_isListening &&
          _state == VoiceState.listening) {
        _startListening();
      }
    });
  }

  Future<void> _startListening() async {
    if (!mounted || _isMicMuted || _isListening || _isInBackground) return;
    if (_state == VoiceState.processing || _state == VoiceState.speaking) return;

    // ASR needs the mic — wait for the analyser to release it before the
    // recognizer opens the input (avoids a mic-ownership race on iOS/Android).
    await _stopAnalyser();
    if (!mounted) return;

    _isListening = true;
    setState(() {
      _state = VoiceState.listening;
      _currentText = 'Listening...';
      _lastSentWords = '';
    });
    _shiftAttentionFor(VoiceState.listening);
    widget.chatController.brain.setListening(true);

    await widget.speechToText.listen(
      onSoundLevelChange: (level) {
        if (!mounted) return;
        final normalized = (level / 9.0).clamp(0.0, 1.0);
        if ((normalized - _micLevel).abs() > 0.01) {
          setState(() => _micLevel = normalized);
        }
      },
      onResult: (result) {
        if (!mounted || _isMicMuted || _isInBackground) return;
        setState(() => _currentText = result.recognizedWords);

        // ── Interrupt detection ────────────────────────────────────────────
        // If user starts speaking while AI is speaking → interrupt immediately
        if (result.recognizedWords.trim().length > 3 &&
            _state == VoiceState.speaking) {
          _triggerInterrupt();
          return;
        }

        if (result.finalResult && result.recognizedWords.trim().isNotEmpty) {
          _processUserSpeech(result.recognizedWords.trim());
        }
      },
      listenOptions: SpeechListenOptions(
        cancelOnError: true,
        partialResults: true,
        listenFor: const Duration(seconds: 50),
        pauseFor: const Duration(milliseconds: 2000),
      ),
    );
  }

  void _triggerInterrupt() {
    debugPrint('[VAD] Interrupting AI mid-response');
    widget.chatController.sendInterrupt();
    setState(() {
      _state = VoiceState.listening;
      _currentText = 'Listening...';
    });
    _shiftAttentionFor(VoiceState.listening);
  }

  void _processUserSpeech(String text) async {
    if (!mounted || _isInBackground) return;
    if (text.isEmpty || text == _lastSentWords) return;

    _lastSentWords = text;
    _isListening = false;
    _restartTimer?.cancel();
    // Sequenced handover: let ASR release the mic, then start the analyser
    // so the very first speaking turn reliably gets band reactivity.
    await widget.speechToText.stop();
    await _ensureAnalyser();
    if (!mounted) return;

    setState(() {
      _state = VoiceState.processing;
      _currentText = 'Thinking...';
    });
    _shiftAttentionFor(VoiceState.processing);

    String? encodedImage;
    if (_isCameraEnabled &&
        _cameraController != null &&
        _cameraController!.value.isInitialized &&
        !_cameraController!.value.isTakingPicture) {
      try {
        final xFile = await _cameraController!.takePicture();
        final bytes = await xFile.readAsBytes();
        encodedImage = base64Encode(bytes);
      } catch (e) {
        debugPrint('Snapshot error: $e');
      }
    }

    widget.chatController.sendMessage(text, base64Image: encodedImage);
  }

  void _toggleMic() {
    setState(() => _isMicMuted = !_isMicMuted);

    if (_isMicMuted) {
      _restartTimer?.cancel();
      widget.speechToText.stop();
      unawaited(_stopAnalyser());
      _isListening = false;
      if (_currentText == 'Listening...') setState(() => _currentText = '');
    } else {
      if (_state == VoiceState.listening) _scheduleListenRestart(delay: 200);
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // CAMERA
  // ──────────────────────────────────────────────────────────────────────────

  Future<void> _initCamera() async {
    if (_cameraInitialising) return;
    _cameraInitialising = true;
    try {
      final cameras = await availableCameras();
      if (cameras.isEmpty) return;
      final controller = CameraController(
        cameras[0],
        ResolutionPreset.medium,
        enableAudio: false,
        imageFormatGroup: ImageFormatGroup.jpeg,
      );
      await controller.initialize();
      if (!mounted) { await controller.dispose(); return; }
      _cameraController = controller;
      setState(() {});
    } catch (e) {
      debugPrint('Camera init error: $e');
    } finally {
      _cameraInitialising = false;
    }
  }

  Future<void> _disposeCamera() async {
    final ctrl = _cameraController;
    _cameraController = null;
    try { await ctrl?.dispose(); } catch (_) {}
  }

  Future<void> _resumeCamera() async {
    if (!_isCameraEnabled) return;
    try {
      await _cameraController?.resumePreview();
      if (mounted) setState(() {});
    } catch (_) {
      await _disposeCamera();
      await _initCamera();
    }
  }

  void _toggleCamera() async {
    if (_isCameraEnabled) {
      setState(() => _isCameraEnabled = false);
    } else {
      final status = await Permission.camera.request();
      if (status == PermissionStatus.granted) {
        if (_cameraController == null || !_cameraController!.value.isInitialized) {
          await _initCamera();
        }
        if (mounted) setState(() => _isCameraEnabled = true);
      }
    }
  }

  void _closeConversation() {
    _restartTimer?.cancel();
    widget.chatController.stopSpeaking();
    widget.speechToText.stop();
    unawaited(_stopAnalyser());
    Navigator.of(context).pop();
  }

  // ──────────────────────────────────────────────────────────────────────────
  // SHARED FFT ANALYSER
  // ──────────────────────────────────────────────────────────────────────────

  Future<void> _ensureAnalyser() async {
    if (_analyser.isRunning) return;
    final ok = await _analyser.start();
    if (!ok) debugPrint('[Overlay] analyser unavailable during talk');
  }

  Future<void> _stopAnalyser() async {
    if (!_analyser.isRunning) return;
    await _analyser.stop();
  }

  /// Live analyser frames (throttled) — drives the orb in the mic-free phases.
  void _onAnalyserLevels(AudioLevels levels) {
    if (!mounted) return;
    final moving = (levels.overall - _analyserLevel).abs() > 0.004 ||
        (levels.mid - _bandMid).abs() > 0.004 ||
        (levels.high - _bandHigh).abs() > 0.004;
    if (moving) {
      setState(() {
        _analyserLevel = levels.overall;
        _bandMid = levels.mid;
        _bandHigh = levels.high;
      });
    }
  }

  // ──────────────────────────────────────────────────────────────────────────
  // BUILD
  // ──────────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final brain = widget.chatController.brain;

    final Color statusColor = _isMicMuted
        ? Colors.redAccent
        : switch (_state) {
            VoiceState.listening  => Colors.greenAccent,
            VoiceState.processing => Colors.orangeAccent,
            VoiceState.speaking   => const Color(0xFF3BAFDA),
          };

    final bool cameraReady = _isCameraEnabled &&
        _cameraController != null &&
        _cameraController!.value.isInitialized;

    return Scaffold(
      backgroundColor: Colors.black.withValues(alpha: 0.94),
      body: Stack(
        children: [
          // ── Camera Background ─────────────────────────────────────────────
          if (cameraReady)
            Positioned.fill(
              child: Stack(
                fit: StackFit.expand,
                children: [
                  CameraPreview(_cameraController!),
                  BackdropFilter(
                    filter: ImageFilter.blur(sigmaX: 15.0, sigmaY: 15.0),
                    child: Container(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [
                            Colors.black.withValues(alpha: 0.2),
                            Colors.black.withValues(alpha: 0.6),
                            Colors.black.withValues(alpha: 0.9),
                          ],
                          stops: const [0.0, 0.5, 1.0],
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),

          SafeArea(
            child: Column(
              children: [
                const SizedBox(height: 20),

                // ── Title ────────────────────────────────────────────────────
                const Text(
                  'Aariya',
                  style: TextStyle(
                    color: Colors.white70,
                    fontSize: 16,
                    fontWeight: FontWeight.w500,
                    letterSpacing: 2.5,
                  ),
                ),

                const Spacer(),

                // ── PRESENCE LAYER ────────────────────────────────────────────
                // Voice-reactive orb + emotion ring with attention shift.
                // While listening the orb is driven by live mic level; while the
                // AI speaks it is driven by the audio-engine energy in the brain.
                AnimatedBuilder(
                  animation: Listenable.merge([brain, ClientBrain.instance]),
                  builder: (context, _) {
                    // Orb energy + spectral bands:
                    //  * listening — speech_to_text owns the mic, so its
                    //    level is the source (analyser cannot run in parallel)
                    //  * processing / speaking — the FFT analyser's bands
                    //    drive the orb (speaking blends in TTS energy)
                    final double orbLevel;
                    final double orbMid;
                    final double orbHigh;
                    if (_state == VoiceState.listening) {
                      orbLevel = _micLevel;
                      orbMid = 0;
                      orbHigh = 0;
                    } else if (_state == VoiceState.speaking &&
                        brain.isSpeaking) {
                      orbLevel = math.max(_analyserLevel, brain.speechEnergy);
                      orbMid = _bandMid;
                      orbHigh = _bandHigh;
                    } else {
                      orbLevel = _analyserLevel;
                      orbMid = _bandMid;
                      orbHigh = _bandHigh;
                    }
                    return AnimatedSlide(
                      offset: Offset(
                        _orbOffset.dx / MediaQuery.of(context).size.width,
                        _orbOffset.dy / MediaQuery.of(context).size.height,
                      ),
                      duration: const Duration(milliseconds: 400),
                      curve: Curves.easeInOut,
                      child: Stack(
                        alignment: Alignment.center,
                        children: [
                          EmotionRing(brain: brain, orbSize: 140),
                          VoiceReactiveOrb(
                            level: orbLevel,
                            bandMid: orbMid,
                            bandHigh: orbHigh,
                            size: 220,
                          ),
                        ],
                      ),
                    );
                  },
                ),

                const SizedBox(height: 32),

                // ── Streaming transcript ──────────────────────────────────────
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 32),
                  child: AnimatedTextStream(
                    text: _currentText,
                    isStreaming: _isStreamingTokens || _state == VoiceState.processing,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.9),
                      fontSize: 17,
                      fontWeight: FontWeight.w400,
                      height: 1.5,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ),

                const Spacer(),

                // ── Bottom panel ──────────────────────────────────────────────
                ClipRRect(
                  borderRadius: const BorderRadius.vertical(top: Radius.circular(32)),
                  child: BackdropFilter(
                    filter: ImageFilter.blur(sigmaX: 10.0, sigmaY: 10.0),
                    child: Container(
                      padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 16),
                      decoration: BoxDecoration(
                        color: Colors.black.withValues(alpha: 0.4),
                        border: Border(
                          top: BorderSide(color: Colors.white.withValues(alpha: 0.1), width: 1),
                        ),
                        borderRadius: const BorderRadius.vertical(top: Radius.circular(32)),
                      ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [

                      // Status pill
                      AnimatedSwitcher(
                        duration: const Duration(milliseconds: 250),
                        child: _isMicMuted
                            ? const _StatusPill(
                                key: ValueKey('muted'),
                                label: 'MICROPHONE MUTED',
                                color: Colors.redAccent,
                              )
                            : _StatusPill(
                                key: ValueKey(_state.name),
                                label: switch (_state) {
                                  VoiceState.listening  => 'LISTENING',
                                  VoiceState.processing => 'THINKING',
                                  VoiceState.speaking   => 'SPEAKING',
                                },
                                color: statusColor,
                              ),
                      ),

                      const SizedBox(height: 20),

                      // Controls row
                      Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          _CircleButton(
                            icon: _isMicMuted ? Icons.mic_off : Icons.mic,
                            color: _isMicMuted ? Colors.redAccent : Colors.white60,
                            onTap: _toggleMic,
                          ),
                          const SizedBox(width: 32),
                          _CircleButton(
                            icon: Icons.videocam,
                            color: _isCameraEnabled
                                ? Colors.greenAccent
                                : Colors.white30,
                            onTap: _toggleCamera,
                          ),
                        ],
                      ),

                      const SizedBox(height: 24),

                      // End button
                      ElevatedButton.icon(
                        onPressed: _closeConversation,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: Colors.redAccent.withValues(alpha: 0.85),
                          padding: const EdgeInsets.symmetric(
                              horizontal: 36, vertical: 14),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(32),
                          ),
                        ),
                        icon: const Icon(Icons.close, color: Colors.white, size: 18),
                        label: const Text(
                          'End Conversation',
                          style: TextStyle(color: Colors.white, fontSize: 15),
                        ),
                      ),
                      const SizedBox(height: 4),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
        ],
      ),
    );
  }
}

// ── Helpers ────────────────────────────────────────────────────────────────────

class _StatusPill extends StatelessWidget {
  final String label;
  final Color color;

  const _StatusPill({super.key, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.5), width: 1),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.bold,
          letterSpacing: 2.0,
        ),
      ),
    );
  }
}

class _CircleButton extends StatelessWidget {
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _CircleButton({
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 56,
        height: 56,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Colors.white.withValues(alpha: 0.06),
          border: Border.all(color: color.withValues(alpha: 0.45), width: 1.5),
        ),
        child: Icon(icon, color: color, size: 26),
      ),
    );
  }
}

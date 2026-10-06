import 'dart:async';
import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:camera/camera.dart';
import 'package:permission_handler/permission_handler.dart';
import '../../../core/audio_analyser.dart';
import '../../../core/state/chat_controller.dart';
import '../../../core/services/websocket_service.dart';
import '../../companion/presentation/companion_presence.dart';
import '../widgets/voice_reactive_orb.dart';
import '../widgets/emotion_ring.dart';
import '../widgets/animated_text_stream.dart';
import '../../../core/brain/client_brain.dart';

part 'voice_overlay_controllers.dart';
part 'voice_overlay_helpers.dart';

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
    with SingleTickerProviderStateMixin, WidgetsBindingObserver, VoiceOverlayControllers {


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
  // BUILD
  // ──────────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final brain = widget.chatController.brain;

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

                const SizedBox(height: 10),

                // ── Companion presence chip (live during the call) ────────────
                // Real mode + trait count from the synoptic; tap for the
                // summary sheet — same chip as the chat app bar.
                CompanionPresenceChip(controller: widget.chatController.brain),

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

                      // Status pill — tinted by the live behavior mode (the
                      // same controller the presence chip reads) so the pill
                      // and chip stay in sync when a state.update changes the
                      // mode mid-call. Muted stays the emergency red; the
                      // AnimatedBuilder repaints on any brain notify so a mode
                      // change without a speech-state change still re-tints.
                      AnimatedBuilder(
                        animation: widget.chatController.brain,
                        builder: (context, _) => AnimatedSwitcher(
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
                                  color: statusPillColor(
                                      _state,
                                      widget.chatController.brain.behaviorMode),
                                ),
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


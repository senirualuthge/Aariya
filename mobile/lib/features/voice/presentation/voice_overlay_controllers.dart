part of 'voice_conversation_overlay.dart';

mixin VoiceOverlayControllers on State<VoiceConversationOverlay> {
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
}

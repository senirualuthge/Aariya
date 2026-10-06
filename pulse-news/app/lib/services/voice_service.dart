import 'dart:async';
import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart' as stt;

import 'voice_intent_service.dart';

enum VoiceCommand {
  readHeadlines,
  readTopStory,
  readTechNews,
  readEconomyNews,
  readGlobalNews,
  readSecurityNews,
  stop,
  nextArticle,
  askQuestion,
  unknown,
}

class VoiceService {
  final stt.SpeechToText _speech = stt.SpeechToText();
  final VoiceIntentService _intentService = VoiceIntentService();
  bool _isListening = false;
  bool _isAvailable = false;
  StreamController<VoiceCommand>? _commandController;

  bool get isListening => _isListening;
  bool get isAvailable => _isAvailable;
  Stream<VoiceCommand>? get commandStream => _commandController?.stream;

  Future<void> initialize() async {
    _isAvailable = await _speech.initialize(
      onStatus: (status) => debugPrint('VoiceService status: $status'),
      onError: (error) => debugPrint('VoiceService error: $error'),
    );
    _commandController = StreamController<VoiceCommand>.broadcast();
    debugPrint('VoiceService initialized: $_isAvailable');
  }

  void startListening() {
    if (!_isAvailable || _isListening) return;

    _isListening = true;
    _speech.listen(
      onResult: (result) {
        if (result.finalResult && result.recognizedWords.isNotEmpty) {
          _classifyCommand(result.recognizedWords);
        }
      },
      listenOptions: stt.SpeechListenOptions(
        listenFor: const Duration(seconds: 10),
        pauseFor: const Duration(seconds: 3),
        partialResults: false,
        localeId: 'en_US',
      ),
    );
  }

  Future<void> _classifyCommand(String text) async {
    final intent = await _intentService.classify(text);
    final command = _mapIntent(intent, text);
    _commandController?.add(command);
  }

  VoiceCommand _mapIntent(VoiceIntentResult intent, String originalText) {
    switch (intent.intent) {
      case 'read_headlines':
        return VoiceCommand.readHeadlines;
      case 'read_top_story':
        return VoiceCommand.readTopStory;
      case 'read_category':
        final cat = intent.params['category'] ?? '';
        switch (cat) {
          case 'tech': return VoiceCommand.readTechNews;
          case 'economy': return VoiceCommand.readEconomyNews;
          case 'global': return VoiceCommand.readGlobalNews;
          case 'security': return VoiceCommand.readSecurityNews;
        }
        return VoiceCommand.unknown;
      case 'stop_reading':
        return VoiceCommand.stop;
      case 'next_article':
        return VoiceCommand.nextArticle;
      case 'ask_question':
        return VoiceCommand.askQuestion;
      default:
        return _parseLocal(originalText);
    }
  }

  VoiceCommand _parseLocal(String text) {
    if (text.contains('read headline') || text.contains('what happened')) {
      return VoiceCommand.readHeadlines;
    }
    if (text.contains('read top story') || text.contains('top story')) {
      return VoiceCommand.readTopStory;
    }
    if (text.contains('tech news') || text.contains('technology')) {
      return VoiceCommand.readTechNews;
    }
    if (text.contains('economy') || text.contains('economic')) {
      return VoiceCommand.readEconomyNews;
    }
    if (text.contains('global') || text.contains('world')) {
      return VoiceCommand.readGlobalNews;
    }
    if (text.contains('security') || text.contains('cyber')) {
      return VoiceCommand.readSecurityNews;
    }
    if (text.contains('stop') || text.contains('silence')) {
      return VoiceCommand.stop;
    }
    if (text.contains('next') || text.contains('skip')) {
      return VoiceCommand.nextArticle;
    }
    if (text.contains('question') || text.contains('ask') || text.contains('what about') || text.contains('tell me about')) {
      return VoiceCommand.askQuestion;
    }
    return VoiceCommand.unknown;
  }

  void stopListening() {
    _isListening = false;
    _speech.stop();
  }

  void dispose() {
    stopListening();
    _commandController?.close();
    _speech.cancel();
  }
}

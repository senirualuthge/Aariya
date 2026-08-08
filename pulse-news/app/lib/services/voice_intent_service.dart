import 'dart:convert';
import 'package:http/http.dart' as http;

import 'api_config.dart';

class VoiceIntentResult {
  final String intent;
  final Map<String, dynamic> params;

  VoiceIntentResult({required this.intent, required this.params});

  factory VoiceIntentResult.fromJson(Map<String, dynamic> json) {
    return VoiceIntentResult(
      intent: json['intent'] as String? ?? 'unknown',
      params: json['params'] as Map<String, dynamic>? ?? {},
    );
  }
}

class VoiceIntentService {
  static final String _baseUrl = ApiConfig.baseUrl;

  Future<VoiceIntentResult> classify(String text) async {
    try {
      final resp = await http.post(
        Uri.parse('$_baseUrl/api/voice/intent')
            .replace(queryParameters: {'text': text}),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body)['data'] as Map<String, dynamic>;
        return VoiceIntentResult.fromJson(data);
      }
    } catch (_) {}
    return VoiceIntentResult(intent: 'unknown', params: {});
  }
}

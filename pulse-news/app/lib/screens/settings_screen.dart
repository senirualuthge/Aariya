import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../services/api_config.dart';
import '../services/session.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  static final String _baseUrl = ApiConfig.baseUrl;

  bool _loading = true;
  Map<String, dynamic> _settings = {};
  final _interestsCtrl = TextEditingController();
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  @override
  void dispose() {
    _interestsCtrl.dispose();
    super.dispose();
  }

  String get _userId => Session.instance.userId;

  Future<void> _loadSettings() async {
    try {
      final resp = await http.get(
        Uri.parse('$_baseUrl/api/user/settings?user_id=$_userId'),
      );
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body)['data'] as Map<String, dynamic>;
        setState(() {
          _settings = data;
          _interestsCtrl.text = (data['interests'] as List?)?.join(', ') ?? '';
          _loading = false;
        });
      }
    } catch (_) {
      setState(() => _loading = false);
    }
  }

  Future<void> _save(String key, dynamic value) async {
    setState(() => _saving = true);
    try {
      final params = <String, String>{'user_id': _userId, key: value.toString()};
      await http.post(Uri.parse('$_baseUrl/api/user/settings').replace(queryParameters: params));
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Saved'), duration: Duration(seconds: 1)),
        );
      }
    } catch (_) {}
    setState(() => _saving = false);
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));

    return Scaffold(
      appBar: AppBar(title: const Text('Settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          const Text('Interests', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          const SizedBox(height: 4),
          TextField(
            controller: _interestsCtrl,
            decoration: const InputDecoration(
              hintText: 'AI, economy, startups...',
              border: OutlineInputBorder(),
            ),
            onSubmitted: (v) => _save('interests', v),
          ),
          const SizedBox(height: 24),

          const Text('Region', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          const SizedBox(height: 4),
          DropdownButtonFormField<String>(
            initialValue: _settings['region'] ?? 'Asia',
            items: ['Asia', 'North America', 'Europe', 'Global']
                .map((r) => DropdownMenuItem(value: r, child: Text(r)))
                .toList(),
            onChanged: (v) => _save('region', v),
            decoration: const InputDecoration(border: OutlineInputBorder()),
          ),
          const SizedBox(height: 24),

          SwitchListTile(
            title: const Text('Risk Mode'),
            subtitle: const Text('Prioritize risk-related news'),
            value: _settings['risk_mode'] ?? true,
            onChanged: (v) => _save('risk_mode', v),
          ),
          const SizedBox(height: 16),

          const Text('Alert Threshold', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          Slider(
            value: (_settings['alert_threshold'] ?? 7).toDouble(),
            min: 1, max: 10, divisions: 9,
            label: '${_settings['alert_threshold'] ?? 7}',
            onChanged: (v) => setState(() => _settings['alert_threshold'] = v.round()),
            onChangeEnd: (v) => _save('alert_threshold', v.round()),
          ),
          const SizedBox(height: 24),

          const Text('Alert Cooldown (minutes)',
              style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          Slider(
            value: (_settings['alert_cooldown_mins'] ?? 30).toDouble(),
            min: 5, max: 1440, divisions: 50,
            label: '${_settings['alert_cooldown_mins'] ?? 30} min',
            onChanged: (v) => setState(() => _settings['alert_cooldown_mins'] = v.round()),
            onChangeEnd: (v) => _save('alert_cooldown_mins', v.round()),
          ),
          const SizedBox(height: 24),

          const Text('TTS Speed', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          Slider(
            value: (_settings['tts_rate'] ?? 0.45).toDouble(),
            min: 0.1, max: 1.0, divisions: 18,
            label: '${((_settings['tts_rate'] ?? 0.45) * 100).round()}%',
            onChanged: (v) => setState(() => _settings['tts_rate'] = v),
            onChangeEnd: (v) => _save('tts_rate', v),
          ),
          const SizedBox(height: 24),

          const Text('TTS Pitch', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          Slider(
            value: (_settings['tts_pitch'] ?? 1.0).toDouble(),
            min: 0.5, max: 2.0, divisions: 15,
            label: '${_settings['tts_pitch'] ?? 1.0}',
            onChanged: (v) => setState(() => _settings['tts_pitch'] = v),
            onChangeEnd: (v) => _save('tts_pitch', v),
          ),
          const SizedBox(height: 24),

          const Text('Theme', style: TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
          DropdownButtonFormField<String>(
            initialValue: _settings['theme'] ?? 'dark',
            items: ['dark', 'light'].map((t) => DropdownMenuItem(value: t, child: Text(t == 'dark' ? 'Dark' : 'Light'))).toList(),
            onChanged: (v) => _save('theme', v),
            decoration: const InputDecoration(border: OutlineInputBorder()),
          ),
          if (_saving)
            const Padding(
              padding: EdgeInsets.only(top: 16),
              child: LinearProgressIndicator(),
            ),
        ],
      ),
    );
  }
}

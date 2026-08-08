import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../services/api_config.dart';

class TrendsScreen extends StatefulWidget {
  const TrendsScreen({super.key});

  @override
  State<TrendsScreen> createState() => _TrendsScreenState();
}

class _TrendsScreenState extends State<TrendsScreen> {
  static final String _baseUrl = ApiConfig.baseUrl;

  bool _loading = true;
  List<dynamic> _trends = [];
  List<dynamic> _predictions = [];
  Timer? _refreshTimer;

  @override
  void initState() {
    super.initState();
    _fetch();
    _refreshTimer = Timer.periodic(const Duration(seconds: 30), (_) => _fetch());
  }

  @override
  void dispose() {
    _refreshTimer?.cancel();
    super.dispose();
  }

  Future<void> _fetch() async {
    try {
      final resp = await Future.wait([
        http.get(Uri.parse('$_baseUrl/api/trends?limit=20')),
        http.get(Uri.parse('$_baseUrl/api/trends/predictions')),
      ]);
      final trends = jsonDecode(resp[0].body)['data'] as List<dynamic>;
      final predictions = jsonDecode(resp[1].body)['data'] as List<dynamic>;
      if (mounted) {
        setState(() {
          _trends = trends;
          _predictions = predictions;
          _loading = false;
        });
      }
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Color _statusColor(String? status) {
    switch (status) {
      case 'emerging': return Colors.blue;
      case 'peaking': return Colors.orange;
      case 'decaying': return Colors.grey;
      default: return Colors.green;
    }
  }

  IconData _statusIcon(String? status) {
    switch (status) {
      case 'emerging': return Icons.trending_up;
      case 'peaking': return Icons.trending_up;
      case 'decaying': return Icons.trending_down;
      default: return Icons.remove;
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) return const Scaffold(body: Center(child: CircularProgressIndicator()));

    return Scaffold(
      appBar: AppBar(
        title: const Text('Trends'),
        actions: [
          IconButton(icon: const Icon(Icons.refresh), onPressed: _fetch),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _fetch,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            const Text('Current Signals', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            ..._trends.map((t) => Card(
                  margin: const EdgeInsets.only(bottom: 8),
                  child: ListTile(
                    leading: Icon(_statusIcon(t['status']), color: _statusColor(t['status'])),
                    title: Text((t['category'] ?? 'other').toString().toUpperCase()),
                    subtitle: Text('Score: ${(t['trend_score'] * 100).round()}%  |  Burst: ${t['burst_ratio']}x'),
                    trailing: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                      decoration: BoxDecoration(
                        color: _statusColor(t['status']).withAlpha(40),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      child: Text(
                        (t['status'] ?? '').toString().toUpperCase(),
                        style: TextStyle(color: _statusColor(t['status']), fontSize: 11, fontWeight: FontWeight.bold),
                      ),
                    ),
                  ),
                )),
            if (_predictions.isNotEmpty) ...[
              const SizedBox(height: 24),
              const Text('ML Predictions', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
              const SizedBox(height: 8),
              ..._predictions.map((p) => Card(
                    margin: const EdgeInsets.only(bottom: 8),
                    child: ListTile(
                      leading: const Icon(Icons.model_training, color: Colors.purple),
                      title: Text((p['category'] ?? 'other').toString().toUpperCase()),
                      subtitle: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('Importance: ${(p['predicted_importance'] * 100).round()}%'),
                          Text('Breaking prob: ${(p['predicted_breaking_prob'] * 100).round()}%'),
                        ],
                      ),
                    ),
                  )),
            ],
          ],
        ),
      ),
    );
  }
}

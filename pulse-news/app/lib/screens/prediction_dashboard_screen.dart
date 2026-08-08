import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

// ─── Data Models ──────────────────────────────────────────────────────────────

class PredictionForecast {
  final String symbol;
  final String direction;
  final double confidence;
  final double uncertainty;
  final double predictedChangePct;
  final int horizon;
  final List<ScenarioItem> scenarios;
  final String action;
  final String rationale;
  final double timestamp;

  const PredictionForecast({
    required this.symbol,
    required this.direction,
    required this.confidence,
    required this.uncertainty,
    required this.predictedChangePct,
    required this.horizon,
    required this.scenarios,
    required this.action,
    required this.rationale,
    required this.timestamp,
  });

  factory PredictionForecast.fromJson(Map<String, dynamic> j) {
    final forecast = j['forecast'] as Map<String, dynamic>? ?? {};
    final conf = j['confidence'] as Map<String, dynamic>? ?? {};
    final meta = j['meta_policy'] as Map<String, dynamic>? ?? {};
    final rawScenarios = j['scenarios'] as List<dynamic>? ?? [];

    return PredictionForecast(
      symbol: j['symbol'] as String? ?? '?',
      direction: forecast['direction'] as String? ?? 'neutral',
      confidence: (conf['overall'] as num?)?.toDouble() ?? 0.0,
      uncertainty: (conf['uncertainty'] as num?)?.toDouble() ?? 1.0,
      predictedChangePct:
          (forecast['predicted_change_pct'] as num?)?.toDouble() ?? 0.0,
      horizon: j['horizon'] as int? ?? 60,
      scenarios: rawScenarios
          .map((s) => ScenarioItem.fromJson(s as Map<String, dynamic>))
          .toList(),
      action: meta['action'] as String? ?? 'hold',
      rationale: meta['explanation'] as String? ?? '',
      timestamp: (j['timestamp'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class ScenarioItem {
  final String name;
  final double probability;
  final double expectedMove;
  const ScenarioItem(
      {required this.name,
      required this.probability,
      required this.expectedMove});
  factory ScenarioItem.fromJson(Map<String, dynamic> j) => ScenarioItem(
        name: j['name'] as String? ?? '?',
        probability: (j['probability'] as num?)?.toDouble() ?? 0.0,
        expectedMove: (j['expected_move_pct'] as num?)?.toDouble() ?? 0.0,
      );
}

class FeedStatus {
  final String status;
  final List<String> symbols;
  final double intervalSeconds;
  final int pendingCount;

  const FeedStatus({
    required this.status,
    required this.symbols,
    required this.intervalSeconds,
    required this.pendingCount,
  });

  factory FeedStatus.fromJson(Map<String, dynamic> j) => FeedStatus(
        status: j['status'] as String? ?? 'unknown',
        symbols: (j['symbols'] as List<dynamic>?)?.cast<String>() ?? [],
        intervalSeconds:
            (j['interval_seconds'] as num?)?.toDouble() ?? 60.0,
        pendingCount: j['pending_count'] as int? ?? 0,
      );
}

// ─── Service ──────────────────────────────────────────────────────────────────

class PredictionService {
  static const _base = 'http://localhost:8000';

  Future<PredictionForecast> fetchPrediction({
    required String symbol,
    required double price,
    String assetClass = 'stock',
  }) async {
    final uri = Uri.parse('$_base/predict/single').replace(queryParameters: {
      'symbol': symbol,
      'price': price.toString(),
      'asset_class': assetClass,
      'horizons': '5,15,60,240',
    });
    final res = await http.post(uri).timeout(const Duration(seconds: 10));
    if (res.statusCode != 200) throw Exception('Prediction failed: ${res.body}');
    return PredictionForecast.fromJson(
        json.decode(res.body) as Map<String, dynamic>);
  }

  Future<FeedStatus> fetchFeedStatus() async {
    final res = await http
        .get(Uri.parse('$_base/predict/feed-status'))
        .timeout(const Duration(seconds: 5));
    if (res.statusCode != 200) throw Exception('Feed status failed');
    return FeedStatus.fromJson(
        json.decode(res.body) as Map<String, dynamic>);
  }

  Future<List<Map<String, dynamic>>> fetchHistory(
      {String? symbol, int limit = 30}) async {
    final params = {'limit': limit.toString()};
    if (symbol != null) params['symbol'] = symbol;
    final uri = Uri.parse('$_base/predict/history')
        .replace(queryParameters: params);
    final res =
        await http.get(uri).timeout(const Duration(seconds: 5));
    if (res.statusCode != 200) return [];
    final body = json.decode(res.body) as Map<String, dynamic>;
    return (body['data'] as List<dynamic>?)
            ?.cast<Map<String, dynamic>>() ??
        [];
  }
}

// ─── Screen ───────────────────────────────────────────────────────────────────

class PredictionDashboardScreen extends StatefulWidget {
  const PredictionDashboardScreen({super.key});

  @override
  State<PredictionDashboardScreen> createState() =>
      _PredictionDashboardScreenState();
}

class _PredictionDashboardScreenState
    extends State<PredictionDashboardScreen>
    with SingleTickerProviderStateMixin {
  final _service = PredictionService();
  final _symbolController = TextEditingController(text: 'AAPL');
  final _priceController = TextEditingController(text: '195.0');
  String _assetClass = 'stock';

  PredictionForecast? _forecast;
  FeedStatus? _feedStatus;
  List<Map<String, dynamic>> _history = [];

  bool _loadingPrediction = false;
  bool _loadingFeed = false;
  String? _error;

  late AnimationController _pulseController;

  Timer? _feedTimer;

  @override
  void initState() {
    super.initState();
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);

    _refreshFeedStatus();
    _loadHistory();
    _feedTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) => _refreshFeedStatus(),
    );
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _feedTimer?.cancel();
    _symbolController.dispose();
    _priceController.dispose();
    super.dispose();
  }

  Future<void> _predict() async {
    final symbol = _symbolController.text.trim().toUpperCase();
    final price = double.tryParse(_priceController.text.trim());
    if (symbol.isEmpty || price == null) {
      setState(() => _error = 'Enter a valid symbol and price.');
      return;
    }
    setState(() {
      _loadingPrediction = true;
      _error = null;
    });
    try {
      final forecast = await _service.fetchPrediction(
        symbol: symbol,
        price: price,
        assetClass: _assetClass,
      );
      setState(() => _forecast = forecast);
      await _loadHistory(symbol: symbol);
    } catch (e) {
      setState(() => _error = e.toString());
    } finally {
      setState(() => _loadingPrediction = false);
    }
  }

  Future<void> _refreshFeedStatus() async {
    setState(() => _loadingFeed = true);
    try {
      final status = await _service.fetchFeedStatus();
      setState(() => _feedStatus = status);
    } catch (_) {}
    setState(() => _loadingFeed = false);
  }

  Future<void> _loadHistory({String? symbol}) async {
    final history = await _service.fetchHistory(
        symbol: symbol ?? _symbolController.text.trim().toUpperCase(),
        limit: 20);
    if (mounted) setState(() => _history = history);
  }

  // ── Colours ────────────────────────────────────────────────────────

  static const _bgColor = Color(0xFF0A0E1A);
  static const _surfaceColor = Color(0xFF141928);
  static const _cardColor = Color(0xFF1C2235);
  static const _accentBlue = Color(0xFF4C9EFF);
  static const _accentGreen = Color(0xFF22D3A0);
  static const _accentRed = Color(0xFFFF5F57);
  static const _accentAmber = Color(0xFFFFB740);
  static const _textPrimary = Color(0xFFE8EDF8);
  static const _textSecondary = Color(0xFF8898B0);

  // ── Build ──────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _bgColor,
      appBar: AppBar(
        backgroundColor: _surfaceColor,
        elevation: 0,
        title: Row(
          children: [
            const Icon(Icons.auto_graph_rounded, color: _accentBlue, size: 22),
            const SizedBox(width: 8),
            const Text(
              'Prediction Engine',
              style: TextStyle(
                color: _textPrimary,
                fontWeight: FontWeight.w700,
                fontSize: 18,
              ),
            ),
          ],
        ),
        actions: [
          _FeedStatusBadge(status: _feedStatus, loading: _loadingFeed),
          const SizedBox(width: 8),
        ],
      ),
      body: CustomScrollView(
        slivers: [
          SliverToBoxAdapter(child: _buildInputCard()),
          SliverToBoxAdapter(
              child: _error != null ? _buildError() : const SizedBox.shrink()),
          SliverToBoxAdapter(
              child: _forecast != null
                  ? _buildForecastPanel()
                  : const SizedBox.shrink()),
          SliverToBoxAdapter(
              child: _history.isNotEmpty
                  ? _buildHistoryPanel()
                  : const SizedBox.shrink()),
          const SliverToBoxAdapter(child: SizedBox(height: 40)),
        ],
      ),
    );
  }

  Widget _buildInputCard() {
    return Container(
      margin: const EdgeInsets.all(16),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _surfaceColor,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: _accentBlue.withValues(alpha: 0.2)),
        boxShadow: [
          BoxShadow(
            color: _accentBlue.withValues(alpha: 0.08),
            blurRadius: 24,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Run Prediction',
            style: TextStyle(
              color: _textPrimary,
              fontWeight: FontWeight.w700,
              fontSize: 16,
            ),
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              Expanded(child: _inputField(_symbolController, 'Symbol', 'AAPL')),
              const SizedBox(width: 12),
              Expanded(
                  child: _inputField(
                      _priceController, 'Current Price', '195.00',
                      isNumeric: true)),
            ],
          ),
          const SizedBox(height: 12),
          _AssetClassSelector(
            selected: _assetClass,
            onChanged: (v) => setState(() => _assetClass = v),
          ),
          const SizedBox(height: 16),
          SizedBox(
            width: double.infinity,
            height: 48,
            child: ElevatedButton(
              onPressed: _loadingPrediction ? null : _predict,
              style: ElevatedButton.styleFrom(
                backgroundColor: _accentBlue,
                foregroundColor: Colors.white,
                shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(14)),
                elevation: 0,
              ),
              child: _loadingPrediction
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(
                          color: Colors.white, strokeWidth: 2),
                    )
                  : const Text(
                      'Run Prediction',
                      style: TextStyle(
                          fontWeight: FontWeight.w700, fontSize: 15),
                    ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _inputField(
    TextEditingController ctrl,
    String label,
    String hint, {
    bool isNumeric = false,
  }) {
    return TextField(
      controller: ctrl,
      keyboardType: isNumeric
          ? const TextInputType.numberWithOptions(decimal: true)
          : TextInputType.text,
      textCapitalization: TextCapitalization.characters,
      style: const TextStyle(color: _textPrimary, fontWeight: FontWeight.w600),
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        labelStyle: const TextStyle(color: _textSecondary, fontSize: 13),
        hintStyle: const TextStyle(color: _textSecondary),
        filled: true,
        fillColor: _cardColor,
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide.none,
        ),
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      ),
    );
  }

  Widget _buildError() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: _accentRed.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: _accentRed.withValues(alpha: 0.4)),
        ),
        child: Row(
          children: [
            const Icon(Icons.error_outline_rounded,
                color: _accentRed, size: 18),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                _error!,
                style: const TextStyle(color: _accentRed, fontSize: 13),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildForecastPanel() {
    final f = _forecast!;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const SizedBox(height: 16),
          _ForecastHeader(forecast: f),
          const SizedBox(height: 12),
          _ConfidenceBar(confidence: f.confidence, uncertainty: f.uncertainty),
          const SizedBox(height: 12),
          if (f.scenarios.isNotEmpty) _ScenarioChart(scenarios: f.scenarios),
          const SizedBox(height: 12),
          if (f.rationale.isNotEmpty) _RationaleCard(rationale: f.rationale, action: f.action),
        ],
      ),
    );
  }

  Widget _buildHistoryPanel() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Recent Predictions',
            style: TextStyle(
              color: _textPrimary,
              fontWeight: FontWeight.w700,
              fontSize: 15,
            ),
          ),
          const SizedBox(height: 10),
          ..._history.map((row) => _HistoryRow(row: row)),
        ],
      ),
    );
  }
}

// ─── Sub-Widgets ──────────────────────────────────────────────────────────────

class _AssetClassSelector extends StatelessWidget {
  final String selected;
  final ValueChanged<String> onChanged;

  static const _items = [
    ('stock', Icons.bar_chart_rounded),
    ('crypto', Icons.currency_bitcoin_rounded),
    ('forex', Icons.currency_exchange_rounded),
    ('commodity', Icons.oil_barrel_rounded),
  ];

  const _AssetClassSelector(
      {required this.selected, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: _items.map((item) {
        final label = item.$1;
        final icon = item.$2;
        final isSelected = selected == label;
        return Expanded(
          child: GestureDetector(
            onTap: () => onChanged(label),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              margin: const EdgeInsets.only(right: 6),
              padding: const EdgeInsets.symmetric(vertical: 8),
              decoration: BoxDecoration(
                color: isSelected
                    ? _PredictionDashboardScreenState._accentBlue
                        .withValues(alpha: 0.2)
                    : _PredictionDashboardScreenState._cardColor,
                borderRadius: BorderRadius.circular(10),
                border: Border.all(
                  color: isSelected
                      ? _PredictionDashboardScreenState._accentBlue
                      : Colors.transparent,
                ),
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(icon,
                      size: 16,
                      color: isSelected
                          ? _PredictionDashboardScreenState._accentBlue
                          : _PredictionDashboardScreenState._textSecondary),
                  const SizedBox(height: 3),
                  Text(
                    label[0].toUpperCase() + label.substring(1),
                    style: TextStyle(
                      fontSize: 10,
                      color: isSelected
                          ? _PredictionDashboardScreenState._accentBlue
                          : _PredictionDashboardScreenState._textSecondary,
                      fontWeight: isSelected
                          ? FontWeight.w700
                          : FontWeight.normal,
                    ),
                  ),
                ],
              ),
            ),
          ),
        );
      }).toList(),
    );
  }
}

class _FeedStatusBadge extends StatelessWidget {
  final FeedStatus? status;
  final bool loading;
  const _FeedStatusBadge({this.status, required this.loading});

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const SizedBox(
        width: 12,
        height: 12,
        child: CircularProgressIndicator(strokeWidth: 1.5, color: Colors.grey),
      );
    }
    final isRunning = status?.status == 'running';
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 8,
          height: 8,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: isRunning
                ? _PredictionDashboardScreenState._accentGreen
                : Colors.grey,
            boxShadow: isRunning
                ? [
                    BoxShadow(
                      color: _PredictionDashboardScreenState._accentGreen
                          .withValues(alpha: 0.6),
                      blurRadius: 6,
                    )
                  ]
                : null,
          ),
        ),
        const SizedBox(width: 6),
        Text(
          isRunning ? 'Feed live' : 'Feed off',
          style: TextStyle(
            color: isRunning
                ? _PredictionDashboardScreenState._accentGreen
                : Colors.grey,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _ForecastHeader extends StatelessWidget {
  final PredictionForecast forecast;
  const _ForecastHeader({required this.forecast});

  Color _dirColor(String d) {
    if (d == 'up') return _PredictionDashboardScreenState._accentGreen;
    if (d == 'down') return _PredictionDashboardScreenState._accentRed;
    return _PredictionDashboardScreenState._accentAmber;
  }

  IconData _dirIcon(String d) {
    if (d == 'up') return Icons.trending_up_rounded;
    if (d == 'down') return Icons.trending_down_rounded;
    return Icons.trending_flat_rounded;
  }

  @override
  Widget build(BuildContext context) {
    final dirColor = _dirColor(forecast.direction);
    final sign = forecast.predictedChangePct >= 0 ? '+' : '';
    final actionColor = forecast.action.toLowerCase() == 'buy'
        ? _PredictionDashboardScreenState._accentGreen
        : forecast.action.toLowerCase() == 'sell'
            ? _PredictionDashboardScreenState._accentRed
            : _PredictionDashboardScreenState._accentAmber;

    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: _PredictionDashboardScreenState._surfaceColor,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: dirColor.withValues(alpha: 0.3)),
        boxShadow: [
          BoxShadow(
            color: dirColor.withValues(alpha: 0.1),
            blurRadius: 24,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: dirColor.withValues(alpha: 0.15),
              shape: BoxShape.circle,
            ),
            child: Icon(_dirIcon(forecast.direction),
                color: dirColor, size: 28),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  forecast.symbol,
                  style: const TextStyle(
                    color: _PredictionDashboardScreenState._textPrimary,
                    fontWeight: FontWeight.w800,
                    fontSize: 22,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  '${forecast.direction.toUpperCase()}  $sign${forecast.predictedChangePct.toStringAsFixed(2)}%',
                  style: TextStyle(
                    color: dirColor,
                    fontWeight: FontWeight.w700,
                    fontSize: 15,
                  ),
                ),
                Text(
                  '${forecast.horizon}m horizon',
                  style: const TextStyle(
                    color: _PredictionDashboardScreenState._textSecondary,
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          ),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              color: actionColor.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: actionColor.withValues(alpha: 0.4)),
            ),
            child: Text(
              forecast.action.toUpperCase(),
              style: TextStyle(
                color: actionColor,
                fontWeight: FontWeight.w800,
                fontSize: 13,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ConfidenceBar extends StatelessWidget {
  final double confidence;
  final double uncertainty;
  const _ConfidenceBar(
      {required this.confidence, required this.uncertainty});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _PredictionDashboardScreenState._surfaceColor,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const Text(
                'Confidence',
                style: TextStyle(
                  color: _PredictionDashboardScreenState._textSecondary,
                  fontSize: 13,
                ),
              ),
              Text(
                '${(confidence * 100).toStringAsFixed(1)}%',
                style: const TextStyle(
                  color: _PredictionDashboardScreenState._textPrimary,
                  fontWeight: FontWeight.w700,
                  fontSize: 14,
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          ClipRRect(
            borderRadius: BorderRadius.circular(6),
            child: TweenAnimationBuilder<double>(
              tween: Tween(begin: 0, end: confidence),
              duration: const Duration(milliseconds: 900),
              curve: Curves.easeOutCubic,
              builder: (_, value, _) => LinearProgressIndicator(
                value: value,
                minHeight: 8,
                backgroundColor:
                    _PredictionDashboardScreenState._cardColor,
                valueColor: AlwaysStoppedAnimation(
                  Color.lerp(
                    _PredictionDashboardScreenState._accentRed,
                    _PredictionDashboardScreenState._accentGreen,
                    value,
                  )!,
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            'Uncertainty: ${(uncertainty * 100).toStringAsFixed(1)}%',
            style: const TextStyle(
              color: _PredictionDashboardScreenState._textSecondary,
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }
}

class _ScenarioChart extends StatelessWidget {
  final List<ScenarioItem> scenarios;
  const _ScenarioChart({required this.scenarios});

  Color _scenarioColor(String name) {
    if (name.contains('bull')) {
      return _PredictionDashboardScreenState._accentGreen;
    }
    if (name.contains('bear')) {
      return _PredictionDashboardScreenState._accentRed;
    }
    if (name.contains('extreme')) {
      return _PredictionDashboardScreenState._accentAmber;
    }
    return _PredictionDashboardScreenState._accentBlue;
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _PredictionDashboardScreenState._surfaceColor,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Scenarios',
            style: TextStyle(
              color: _PredictionDashboardScreenState._textSecondary,
              fontSize: 13,
            ),
          ),
          const SizedBox(height: 12),
          ...scenarios.map((s) {
            final color = _scenarioColor(s.name);
            final sign = s.expectedMove >= 0 ? '+' : '';
            return Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(
                children: [
                  SizedBox(
                    width: 68,
                    child: Text(
                      s.name.toUpperCase(),
                      style: TextStyle(
                        color: color,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(4),
                      child: TweenAnimationBuilder<double>(
                        tween: Tween(begin: 0, end: s.probability),
                        duration: const Duration(milliseconds: 800),
                        curve: Curves.easeOutCubic,
                        builder: (_, val, _) => LinearProgressIndicator(
                          value: val,
                          minHeight: 6,
                          backgroundColor:
                              _PredictionDashboardScreenState._cardColor,
                          valueColor: AlwaysStoppedAnimation(
                              color.withValues(alpha: 0.7)),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 10),
                  SizedBox(
                    width: 50,
                    child: Text(
                      '$sign${s.expectedMove.toStringAsFixed(1)}%',
                      style: TextStyle(
                        color: color,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                      ),
                      textAlign: TextAlign.right,
                    ),
                  ),
                  const SizedBox(width: 6),
                  Text(
                    '${(s.probability * 100).toStringAsFixed(0)}%',
                    style: const TextStyle(
                      color:
                          _PredictionDashboardScreenState._textSecondary,
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
            );
          }),
        ],
      ),
    );
  }
}

class _RationaleCard extends StatelessWidget {
  final String rationale;
  final String action;
  const _RationaleCard({required this.rationale, required this.action});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: _PredictionDashboardScreenState._surfaceColor,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.psychology_rounded,
            color: _PredictionDashboardScreenState._accentBlue,
            size: 20,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              rationale.isNotEmpty ? rationale : 'No rationale provided.',
              style: const TextStyle(
                color: _PredictionDashboardScreenState._textPrimary,
                fontSize: 13,
                height: 1.5,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HistoryRow extends StatelessWidget {
  final Map<String, dynamic> row;
  const _HistoryRow({required this.row});

  Color _dirColor(String? d) {
    if (d == 'up') return _PredictionDashboardScreenState._accentGreen;
    if (d == 'down') return _PredictionDashboardScreenState._accentRed;
    return _PredictionDashboardScreenState._accentAmber;
  }

  @override
  Widget build(BuildContext context) {
    final symbol = row['symbol'] as String? ?? '?';
    final direction = row['direction'] as String? ?? 'neutral';
    final conf = (row['confidence'] as num?)?.toDouble() ?? 0.0;
    final pct = (row['predicted_change_pct'] as num?)?.toDouble() ?? 0.0;
    final sign = pct >= 0 ? '+' : '';
    final dirColor = _dirColor(direction);

    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
      decoration: BoxDecoration(
        color: _PredictionDashboardScreenState._cardColor,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Row(
        children: [
          Text(
            symbol,
            style: const TextStyle(
              color: _PredictionDashboardScreenState._textPrimary,
              fontWeight: FontWeight.w700,
              fontSize: 14,
            ),
          ),
          const SizedBox(width: 10),
          Icon(
            direction == 'up'
                ? Icons.arrow_upward_rounded
                : direction == 'down'
                    ? Icons.arrow_downward_rounded
                    : Icons.remove_rounded,
            color: dirColor,
            size: 14,
          ),
          const SizedBox(width: 4),
          Text(
            '$sign${pct.toStringAsFixed(2)}%',
            style: TextStyle(
              color: dirColor,
              fontWeight: FontWeight.w600,
              fontSize: 13,
            ),
          ),
          const Spacer(),
          Text(
            'Conf ${(conf * 100).toStringAsFixed(0)}%',
            style: const TextStyle(
              color: _PredictionDashboardScreenState._textSecondary,
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }
}

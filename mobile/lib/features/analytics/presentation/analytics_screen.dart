import 'dart:async';
import 'package:flutter/material.dart';
import '../../../core/services/websocket_service.dart';
import '../../../core/services/connection_monitor.dart';

part 'analytics_cards.dart';
part 'analytics_widgets.dart';

// ── Config ─────────────────────────────────────────────────────────────────────
const _kBackground  = Color(0xFF0A0812);
const _kSurface     = Color(0xFF110F1E);
const _kCyan        = Color(0xFF00E5FF);
const _kGreen       = Color(0xFF2ecc71);
const _kBlue        = Color(0xFF4a9eff);
const _kPurple      = Color(0xFFb44fff);
const _kGold        = Color(0xFFffc800);
const _kRed         = Color(0xFFE74C5E);
const _kAmber       = Color(0xFFFF9800);
const int _kHistory = 40;

// Animation duration for smooth real-time transitions
const _kAnim = Duration(milliseconds: 700);

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key});
  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen>
    with SingleTickerProviderStateMixin {
  // ── Live metrics ────────────────────────────────────────────────────────────
  double _cpu         = 0;
  double _ram         = 0;
  double _ramUsedGb   = 0;
  double _ramTotalGb  = 0;
  double _trust       = 0.5;
  int    _agentsActive = 0;
  String _emotion     = 'neutral';
  List<_AgentData> _agents = [];

  // ── History buffers ─────────────────────────────────────────────────────────
  final List<double> _cpuHistory = [];
  final List<double> _ramHistory = [];
  final List<double> _rttHistory = [];
  int    _rttMs  = 0;
  int    _rttMin = 9999;
  int    _rttMax = 0;
  double _rttAvg = 0;

  // ── Banner ──────────────────────────────────────────────────────────────────
  int _newBanner = 0;

  // ── Animation ───────────────────────────────────────────────────────────────
  late final AnimationController _pulseCtrl;
  StreamSubscription<Map<String, dynamic>>? _sub;

  @override
  void initState() {
    super.initState();
    _pulseCtrl = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 2),
    )..repeat(reverse: true);
    _sub = WebSocketService.instance.analyticsStream.listen(_onFrame);
  }

  void _push(List<double> buf, double val) {
    buf.add(val);
    if (buf.length > _kHistory) buf.removeAt(0);
  }

  void _onFrame(Map<String, dynamic> data) {
    if (!mounted) return;

    // RTT
    final serverTs = data['server_ts'] as double?;
    if (serverTs != null) {
      final rtt = ((DateTime.now().millisecondsSinceEpoch / 1000.0 - serverTs) * 1000)
          .round().abs();
      if (rtt < 5000) {
        _rttMs = rtt;
        _push(_rttHistory, rtt.toDouble());
        if (rtt < _rttMin) _rttMin = rtt;
        if (rtt > _rttMax) _rttMax = rtt;
        if (_rttHistory.isNotEmpty) {
          _rttAvg = _rttHistory.reduce((a, b) => a + b) / _rttHistory.length;
        }
      }
    }

    // Agent-discovered push
    if (data['type'] == 'agent_discovered') {
      final raw = data['agents'];
      if (raw is List) {
        final discovered = raw.whereType<Map<String, dynamic>>().toList();
        setState(() {
          for (final a in discovered) {
            final name = a['name'] as String? ?? '';
            _agents.removeWhere((e) => e.name == name);
            _agents.insert(0, _AgentData.fromMap(a));
          }
          _agentsActive = data['agents_active'] as int? ?? _agentsActive;
          _newBanner = discovered.length;
        });
        Future.delayed(const Duration(seconds: 3),
            () { if (mounted) setState(() => _newBanner = 0); });
      }
      return;
    }

    // Regular tick
    setState(() {
      _cpu        = (data['cpu']          as num? ?? _cpu).toDouble();
      _ram        = (data['ram']          as num? ?? _ram).toDouble();
      _ramUsedGb  = (data['ram_used_gb']  as num? ?? _ramUsedGb).toDouble();
      _ramTotalGb = (data['ram_total_gb'] as num? ?? _ramTotalGb).toDouble();
      _trust      = (data['trust']        as num? ?? _trust).toDouble();
      _emotion    = data['emotion'] as String? ?? _emotion;
      _agentsActive = data['agents_active'] as int? ?? _agentsActive;
      _push(_cpuHistory, _cpu);
      _push(_ramHistory, _ram);

      final rawAgents = data['agents'];
      if (rawAgents is List) {
        _agents = rawAgents
            .whereType<Map<String, dynamic>>()
            .map(_AgentData.fromMap)
            .toList();
      }
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    _pulseCtrl.dispose();
    super.dispose();
  }

  // ── UI ─────────────────────────────────────────────────────────────────────
  Color _cpuColor([double? v]) {
    final x = v ?? _cpu;
    return x > 85 ? _kRed : x > 60 ? _kAmber : _kCyan;
  }

  Color _ramColor([double? v]) {
    final x = v ?? _ram;
    return x > 90 ? _kRed : x > 70 ? _kAmber : const Color(0xFF00BFA5);
  }

  Color _rttColor([int? v]) {
    final x = v ?? _rttMs;
    return x == 0 ? Colors.white24 : x < 80 ? _kGreen : x < 250 ? _kAmber : _kRed;
  }

  Color _emotionColor(String e) => const {
    'joy':      Color(0xFFFDD835),
    'trust':    Color(0xFF3BAFDA),
    'surprise': Color(0xFFAB47BC),
    'fear':     Color(0xFF616161),
    'sadness':  Color(0xFF5C6BC0),
    'anger':    _kRed,
    'disgust':  Color(0xFF66BB6A),
    'neutral':  Color(0xFF546E7A),
  }[e.toLowerCase()] ?? const Color(0xFF546E7A);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: _kBackground,
      body: Column(
        children: [
          _buildHeader(),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 10, 16, 36),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (_newBanner > 0) ...[
                    _DiscoveryBanner(count: _newBanner),
                    const SizedBox(height: 14),
                  ],
                  _buildQuickStats(),
                  const SizedBox(height: 16),
                  _buildBrainRow(),
                  const SizedBox(height: 14),
                  _buildResourceCard(
                    section: 'PROCESSOR',
                    label: 'CPU',
                    value: _cpu / 100,
                    rawValue: _cpu,
                    color: _cpuColor(),
                    history: _cpuHistory,
                    subtitle: '${_cpu.toStringAsFixed(1)}%',
                  ),
                  const SizedBox(height: 12),
                  _buildResourceCard(
                    section: 'MEMORY',
                    label: 'RAM',
                    value: _ram / 100,
                    rawValue: _ram,
                    color: _ramColor(),
                    history: _ramHistory,
                    subtitle:
                        '${_ramUsedGb.toStringAsFixed(1)} / ${_ramTotalGb.toStringAsFixed(1)} GB',
                    extra: '${_ram.toStringAsFixed(1)}%',
                  ),
                  const SizedBox(height: 16),
                  _buildRttCard(),
                  const SizedBox(height: 16),
                  _buildAgentSection(),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  // ── HEADER ─────────────────────────────────────────────────────────────────
  Widget _buildHeader() {
    return Container(
      padding: EdgeInsets.only(
        top: MediaQuery.of(context).padding.top + 10,
        left: 20, right: 20, bottom: 14,
      ),
      decoration: BoxDecoration(
        color: _kSurface,
        border: Border(bottom: BorderSide(color: _kCyan.withValues(alpha: 0.15))),
      ),
      child: Row(
        children: [
          AnimatedBuilder(
            animation: _pulseCtrl,
            builder: (_, __) => Container(
              width: 8, height: 8,
              decoration: BoxDecoration(
                color: _kGreen,
                shape: BoxShape.circle,
                boxShadow: [
                  BoxShadow(
                    color: _kGreen.withValues(alpha: 0.35 + 0.45 * _pulseCtrl.value),
                    blurRadius: 8 + 5 * _pulseCtrl.value,
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 10),
          const Text('SYSTEM ANALYTICS',
              style: TextStyle(
                color: _kCyan, fontWeight: FontWeight.bold,
                fontSize: 13, letterSpacing: 3,
              )),
          const Spacer(),
          _ConnectionBadge(),
        ],
      ),
    );
  }

  // ── QUICK STATS STRIP ──────────────────────────────────────────────────────
  Widget _buildQuickStats() {
    return Row(
      children: [
        Expanded(child: _QuickStat(
          label: 'AGENTS',
          value: '$_agentsActive',
          color: _kCyan,
        )),
        const SizedBox(width: 8),
        // Animated trust quick stat
        Expanded(child: TweenAnimationBuilder<double>(
          tween: Tween<double>(end: _trust),
          duration: _kAnim,
          curve: Curves.easeOutCubic,
          builder: (_, v, __) => _QuickStat(
            label: 'TRUST',
            value: '${(v * 100).toInt()}%',
            color: _kBlue,
          ),
        )),
        const SizedBox(width: 8),
        // Animated RTT quick stat
        Expanded(child: TweenAnimationBuilder<double>(
          tween: Tween<double>(end: _rttMs.toDouble()),
          duration: _kAnim,
          curve: Curves.easeOutCubic,
          builder: (_, v, __) => _QuickStat(
            label: 'RTT',
            value: _rttMs == 0 ? '–' : '${v.toInt()}ms',
            color: _rttColor(),
          ),
        )),
        const SizedBox(width: 8),
        Expanded(child: _QuickStat(
          label: 'STATE',
          value: _emotion.toUpperCase(),
          color: _emotionColor(_emotion),
        )),
      ],
    );
  }

  // ── BRAIN STATE ROW ────────────────────────────────────────────────────────
  Widget _buildBrainRow() {
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Trust arc — fully animated
          Expanded(
            child: _Card(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _Label('TRUST SCORE'),
                  const SizedBox(height: 14),
                  Center(
                    child: TweenAnimationBuilder<double>(
                      tween: Tween<double>(end: _trust),
                      duration: _kAnim,
                      curve: Curves.easeOutCubic,
                      builder: (_, animTrust, __) => AnimatedBuilder(
                        animation: _pulseCtrl,
                        builder: (_, __) => SizedBox(
                          width: 90, height: 90,
                          child: Stack(
                            alignment: Alignment.center,
                            children: [
                              // Background ring
                              SizedBox(
                                width: 90, height: 90,
                                child: CircularProgressIndicator(
                                  value: 1.0,
                                  strokeWidth: 7,
                                  color: Colors.white.withValues(alpha: 0.05),
                                ),
                              ),
                              // Animated value ring
                              SizedBox(
                                width: 90, height: 90,
                                child: CircularProgressIndicator(
                                  value: animTrust,
                                  strokeWidth: 7,
                                  backgroundColor: Colors.transparent,
                                  valueColor: AlwaysStoppedAnimation<Color>(
                                    Color.lerp(_kBlue, _kCyan, _pulseCtrl.value)!,
                                  ),
                                ),
                              ),
                              // Animated number
                              Column(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Text(
                                    '${(animTrust * 100).toInt()}',
                                    style: const TextStyle(
                                      color: Colors.white,
                                      fontWeight: FontWeight.bold,
                                      fontSize: 24,
                                      height: 1,
                                    ),
                                  ),
                                  Text('%',
                                      style: TextStyle(
                                        color: Colors.white.withValues(alpha: 0.35),
                                        fontSize: 11,
                                      )),
                                ],
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(width: 12),

          // Emotion + Agents
          Expanded(
            child: _Card(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const _Label('BRAIN STATE'),
                  const SizedBox(height: 14),
                  Center(
                    child: Column(
                      children: [
                        // AnimatedSwitcher makes emotion chip fade when it changes
                        AnimatedSwitcher(
                          duration: const Duration(milliseconds: 400),
                          transitionBuilder: (child, anim) => FadeTransition(
                            opacity: anim,
                            child: ScaleTransition(scale: anim, child: child),
                          ),
                          child: Container(
                            key: ValueKey(_emotion),
                            padding: const EdgeInsets.symmetric(
                                horizontal: 14, vertical: 7),
                            decoration: BoxDecoration(
                              color: _emotionColor(_emotion).withValues(alpha: 0.15),
                              borderRadius: BorderRadius.circular(24),
                              border: Border.all(
                                  color: _emotionColor(_emotion).withValues(alpha: 0.5)),
                            ),
                            child: Text(
                              _emotion.toUpperCase(),
                              style: TextStyle(
                                color: _emotionColor(_emotion),
                                fontWeight: FontWeight.bold,
                                fontSize: 12,
                                letterSpacing: 2,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 12),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            const Icon(Icons.hub_outlined,
                                color: Colors.tealAccent, size: 14),
                            const SizedBox(width: 5),
                            // Animated agent count
                            TweenAnimationBuilder<double>(
                              tween: Tween<double>(end: _agentsActive.toDouble()),
                              duration: _kAnim,
                              curve: Curves.easeOutCubic,
                              builder: (_, v, __) => Text(
                                '${v.round()} AGENTS',
                                style: const TextStyle(
                                  color: Colors.tealAccent,
                                  fontWeight: FontWeight.bold,
                                  fontSize: 12,
                                  letterSpacing: 1,
                                ),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

}


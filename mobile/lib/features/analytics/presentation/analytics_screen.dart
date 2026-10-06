import 'dart:async';
import 'package:flutter/material.dart';
import '../../services/websocket_service.dart';
import '../../services/connection_monitor.dart';

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

  // ── RESOURCE CARD ──────────────────────────────────────────────────────────
  Widget _buildResourceCard({
    required String section,
    required String label,
    required double value,
    required double rawValue,
    required Color color,
    required List<double> history,
    required String subtitle,
    String? extra,
  }) {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _Label(section),
              // Animated value label
              TweenAnimationBuilder<double>(
                tween: Tween<double>(end: rawValue),
                duration: _kAnim,
                curve: Curves.easeOutCubic,
                builder: (_, v, __) => Row(
                  children: [
                    if (extra != null) ...[
                      Text(
                        '${v.toStringAsFixed(1)}%',
                        style: TextStyle(
                          color: color.withValues(alpha: 0.6),
                          fontSize: 11,
                          fontFamily: 'monospace',
                        ),
                      ),
                      const SizedBox(width: 8),
                    ],
                    Text(
                      extra == null ? '${v.toStringAsFixed(1)}%' : subtitle,
                      style: TextStyle(
                        color: color,
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          // Animated progress bar with gradient glow
          TweenAnimationBuilder<double>(
            tween: Tween<double>(end: value.clamp(0.0, 1.0)),
            duration: _kAnim,
            curve: Curves.easeOutCubic,
            builder: (_, v, __) => Container(
              height: 8,
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.07),
                borderRadius: BorderRadius.circular(6),
              ),
              child: FractionallySizedBox(
                alignment: Alignment.centerLeft,
                widthFactor: v,
                child: Container(
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(6),
                    gradient: LinearGradient(
                      colors: [color.withValues(alpha: 0.7), color],
                    ),
                    boxShadow: [
                      BoxShadow(color: color.withValues(alpha: 0.45), blurRadius: 6),
                    ],
                  ),
                ),
              ),
            ),
          ),
          if (history.length > 2) ...[
            const SizedBox(height: 10),
            SizedBox(
              height: 36,
              child: CustomPaint(
                painter: _SparklinePainter(
                  data: List.of(history),
                  color: color,
                  maxVal: 100,
                ),
                size: const Size(double.infinity, 36),
              ),
            ),
          ],
        ],
      ),
    );
  }

  // ── RTT CARD ───────────────────────────────────────────────────────────────
  Widget _buildRttCard() {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              const _Label('NETWORK  ·  ROUND-TRIP TIME'),
              TweenAnimationBuilder<double>(
                tween: Tween<double>(end: _rttMs.toDouble()),
                duration: _kAnim,
                curve: Curves.easeOutCubic,
                builder: (_, v, __) => Row(
                  children: [
                    Icon(Icons.wifi, color: _rttColor(), size: 15),
                    const SizedBox(width: 6),
                    Text(
                      _rttMs == 0 ? 'Awaiting...' : '${v.toInt()} ms',
                      style: TextStyle(
                        color: _rttColor(),
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        fontFamily: 'monospace',
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          // Live RTT sparkline
          SizedBox(
            height: 72,
            child: _rttHistory.length < 2
                ? Center(
                    child: Text(
                      'Collecting samples...',
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.2), fontSize: 12),
                    ),
                  )
                : CustomPaint(
                    painter: _SparklinePainter(
                      data: List.of(_rttHistory),
                      color: _rttColor(),
                      maxVal: (_rttMax * 1.5).clamp(100, 2000).toDouble(),
                      fillArea: true,
                      showDots: true,
                    ),
                    size: const Size(double.infinity, 72),
                  ),
          ),
          // Stats row — fully animated
          if (_rttHistory.length > 2) ...[
            const SizedBox(height: 10),
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _buildRttStat('MIN',
                  TweenAnimationBuilder<double>(
                    tween: Tween<double>(end: _rttMin.toDouble()),
                    duration: _kAnim,
                    builder: (_, v, __) =>
                        Text('${v.toInt()}ms', style: _rttStatStyle(_kGreen)),
                  ),
                ),
                _vDivider(),
                _buildRttStat('AVG',
                  TweenAnimationBuilder<double>(
                    tween: Tween<double>(end: _rttAvg),
                    duration: _kAnim,
                    builder: (_, v, __) =>
                        Text('${v.toInt()}ms', style: _rttStatStyle(_kAmber)),
                  ),
                ),
                _vDivider(),
                _buildRttStat('MAX',
                  TweenAnimationBuilder<double>(
                    tween: Tween<double>(end: _rttMax.toDouble()),
                    duration: _kAnim,
                    builder: (_, v, __) =>
                        Text('${v.toInt()}ms', style: _rttStatStyle(_kRed)),
                  ),
                ),
                _vDivider(),
                _buildRttStat(
                  'QUALITY',
                  Text(
                    _rttAvg < 80 ? 'EXCELLENT' : _rttAvg < 200 ? 'GOOD' : 'POOR',
                    style: _rttStatStyle(
                        _rttAvg < 80 ? _kGreen : _rttAvg < 200 ? _kAmber : _kRed),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildRttStat(String label, Widget valueWidget) => Column(
    children: [
      valueWidget,
      const SizedBox(height: 2),
      Text(label,
          style: TextStyle(
            color: Colors.white.withValues(alpha: 0.28),
            fontSize: 9,
            letterSpacing: 1.5,
          )),
    ],
  );

  static TextStyle _rttStatStyle(Color c) => TextStyle(
    color: c,
    fontWeight: FontWeight.bold,
    fontSize: 13,
    fontFamily: 'monospace',
  );

  static Widget _vDivider() => Container(
    width: 1, height: 28,
    color: Colors.white.withValues(alpha: 0.08),
  );

  // ── AGENTS ─────────────────────────────────────────────────────────────────
  Widget _buildAgentSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            const _Label('AGENT REGISTRY'),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
              decoration: BoxDecoration(
                color: _kCyan.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: _kCyan.withValues(alpha: 0.28)),
              ),
              child: TweenAnimationBuilder<double>(
                tween: Tween<double>(end: _agentsActive.toDouble()),
                duration: _kAnim,
                builder: (_, v, __) => Text(
                  '${v.round()} ACTIVE',
                  style: const TextStyle(
                    color: _kCyan,
                    fontSize: 10,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.5,
                  ),
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 12),
        // AnimatedList would be ideal, but we use AnimatedSwitcher per card
        _agents.isEmpty
            ? _EmptyAgentPlaceholder()
            : Column(
                children: _agents
                    .map((a) => Padding(
                          padding: const EdgeInsets.only(bottom: 10),
                          child: _AgentCard(agent: a),
                        ))
                    .toList(),
              ),
      ],
    );
  }
}

// ── Sparkline painter ─────────────────────────────────────────────────────────
class _SparklinePainter extends CustomPainter {
  final List<double> data;
  final Color color;
  final double maxVal;
  final bool fillArea;
  final bool showDots;

  const _SparklinePainter({
    required this.data,
    required this.color,
    required this.maxVal,
    this.fillArea = false,
    this.showDots = false,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (data.length < 2) return;

    final linePaint = Paint()
      ..color = color
      ..strokeWidth = 1.8
      ..style = PaintingStyle.stroke
      ..strokeCap = StrokeCap.round
      ..strokeJoin = StrokeJoin.round;

    final fillPaint = Paint()
      ..shader = LinearGradient(
        begin: Alignment.topCenter,
        end: Alignment.bottomCenter,
        colors: [color.withValues(alpha: 0.28), Colors.transparent],
      ).createShader(Rect.fromLTWH(0, 0, size.width, size.height));

    final pts = <Offset>[];
    for (int i = 0; i < data.length; i++) {
      final x = i / (data.length - 1) * size.width;
      final y = size.height - (data[i] / maxVal).clamp(0.0, 1.0) * size.height;
      pts.add(Offset(x, y));
    }

    // Smooth cubic bezier path
    final path     = Path()..moveTo(pts[0].dx, pts[0].dy);
    final fillPath = Path()
      ..moveTo(pts[0].dx, size.height)
      ..lineTo(pts[0].dx, pts[0].dy);

    for (int i = 0; i < pts.length - 1; i++) {
      final dx = (pts[i + 1].dx - pts[i].dx) / 3;
      final cp1 = Offset(pts[i].dx + dx, pts[i].dy);
      final cp2 = Offset(pts[i + 1].dx - dx, pts[i + 1].dy);
      path.cubicTo(cp1.dx, cp1.dy, cp2.dx, cp2.dy, pts[i + 1].dx, pts[i + 1].dy);
      fillPath.cubicTo(cp1.dx, cp1.dy, cp2.dx, cp2.dy, pts[i + 1].dx, pts[i + 1].dy);
    }

    if (fillArea) {
      fillPath..lineTo(pts.last.dx, size.height)..close();
      canvas.drawPath(fillPath, fillPaint);
    }
    canvas.drawPath(path, linePaint);

    // Trailing dot with glow
    if (showDots && pts.isNotEmpty) {
      canvas.drawCircle(
          pts.last, 6,
          Paint()
            ..color = color.withValues(alpha: 0.3)
            ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 5));
      canvas.drawCircle(pts.last, 3, Paint()..color = color);
    }
  }

  @override
  bool shouldRepaint(_SparklinePainter old) => old.data != data;
}

// ── Agent data model ──────────────────────────────────────────────────────────
class _AgentData {
  final String name, kind, status, detection, firstSeen;
  const _AgentData({
    required this.name, required this.kind, required this.status,
    required this.detection, required this.firstSeen,
  });
  factory _AgentData.fromMap(Map<String, dynamic> m) => _AgentData(
    name:      m['name']       as String? ?? 'Unknown',
    kind:      m['kind']       as String? ?? 'unknown',
    status:    m['status']     as String? ?? 'existing',
    detection: m['detection']  as String? ?? '',
    firstSeen: m['first_seen'] as String? ?? '',
  );
}

// ── Agent card ────────────────────────────────────────────────────────────────
class _AgentCard extends StatelessWidget {
  final _AgentData agent;
  const _AgentCard({required this.agent});

  static const _detectionColors = {
    'inheritance': _kGreen,
    'folder':      _kBlue,
    'decorator':   _kPurple,
  };
  static const _statusBorder = {
    'new':      _kGold,
    'existing': Color(0xFF2a2a4a),
    'removed':  Color(0xFFff3c3c),
  };
  static const _kindIcons = {
    'class':    Icons.hub_outlined,
    'function': Icons.functions_outlined,
    'module':   Icons.layers_outlined,
  };

  String _fmt(String iso) {
    if (iso.isEmpty) return '–';
    try {
      final dt = DateTime.parse(iso).toLocal();
      return '${dt.hour.toString().padLeft(2, '0')}:${dt.minute.toString().padLeft(2, '0')}';
    } catch (_) { return '–'; }
  }

  @override
  Widget build(BuildContext context) {
    final accent  = _detectionColors[agent.detection] ?? _kBlue;
    final border  = _statusBorder[agent.status]        ?? const Color(0xFF2a2a4a);
    final icon    = _kindIcons[agent.kind]             ?? Icons.circle_outlined;
    final isNew   = agent.status == 'new';
    final isGone  = agent.status == 'removed';

    return AnimatedOpacity(
      opacity: isGone ? 0.4 : 1.0,
      duration: const Duration(milliseconds: 400),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
        decoration: BoxDecoration(
          color: accent.withValues(alpha: 0.05),
          borderRadius: BorderRadius.circular(14),
          border: Border.all(
            color: isNew ? border.withValues(alpha: 0.9) : border.withValues(alpha: 0.3),
            width: isNew ? 1.2 : 1,
          ),
          boxShadow: isNew
              ? [BoxShadow(color: _kGold.withValues(alpha: 0.2), blurRadius: 14)]
              : [],
        ),
        child: Row(
          children: [
            Container(
              width: 38, height: 38,
              decoration: BoxDecoration(
                color: accent.withValues(alpha: 0.12),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Icon(icon, color: accent, size: 20),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(children: [
                    Expanded(
                      child: Text(
                        agent.name,
                        style: const TextStyle(
                          color: Colors.white, fontWeight: FontWeight.w600, fontSize: 13,
                        ),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    if (isNew)
                      Container(
                        margin: const EdgeInsets.only(left: 6),
                        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                        decoration: BoxDecoration(
                          color: _kGold.withValues(alpha: 0.18),
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Text('NEW',
                            style: TextStyle(color: _kGold, fontSize: 9,
                                fontWeight: FontWeight.bold, letterSpacing: 1.2)),
                      ),
                  ]),
                  const SizedBox(height: 4),
                  Row(children: [
                    _MiniTag(agent.kind.toUpperCase(), accent),
                    if (agent.detection.isNotEmpty) ...[
                      const SizedBox(width: 5),
                      _MiniTag(agent.detection, accent.withValues(alpha: 0.65)),
                    ],
                    const Spacer(),
                    Text(_fmt(agent.firstSeen),
                        style: TextStyle(
                          color: Colors.white.withValues(alpha: 0.22),
                          fontSize: 10, fontFamily: 'monospace',
                        )),
                  ]),
                ],
              ),
            ),
            const SizedBox(width: 10),
            Container(
              width: 8, height: 8,
              decoration: BoxDecoration(
                color: border, shape: BoxShape.circle,
                boxShadow: [BoxShadow(color: border.withValues(alpha: 0.5), blurRadius: 6)],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _MiniTag extends StatelessWidget {
  final String label;
  final Color color;
  const _MiniTag(this.label, this.color);
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(6),
    ),
    child: Text(label,
        style: TextStyle(color: color, fontSize: 9,
            letterSpacing: 0.8, fontWeight: FontWeight.w600)),
  );
}

// ── Shared primitives ─────────────────────────────────────────────────────────
class _Card extends StatelessWidget {
  final Widget child;
  const _Card({required this.child});
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      color: _kSurface,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: Colors.white.withValues(alpha: 0.07)),
    ),
    child: child,
  );
}

class _Label extends StatelessWidget {
  final String text;
  const _Label(this.text);
  @override
  Widget build(BuildContext context) => Text(text,
      style: TextStyle(
        color: Colors.white.withValues(alpha: 0.32), fontSize: 10,
        letterSpacing: 2, fontWeight: FontWeight.w600,
      ));
}

class _QuickStat extends StatelessWidget {
  final String label, value;
  final Color color;
  const _QuickStat({required this.label, required this.value, required this.color});
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 10),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.07),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: color.withValues(alpha: 0.2)),
    ),
    child: Column(children: [
      Text(value,
          style: TextStyle(color: color, fontWeight: FontWeight.bold,
              fontSize: 14, fontFamily: 'monospace'),
          maxLines: 1, overflow: TextOverflow.ellipsis),
      const SizedBox(height: 3),
      Text(label,
          style: TextStyle(color: Colors.white.withValues(alpha: 0.28),
              fontSize: 9, letterSpacing: 1.5)),
    ]),
  );
}

class _DiscoveryBanner extends StatelessWidget {
  final int count;
  const _DiscoveryBanner({required this.count});
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
    decoration: BoxDecoration(
      color: _kGold.withValues(alpha: 0.1),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: _kGold.withValues(alpha: 0.45)),
    ),
    child: Row(children: [
      const Icon(Icons.new_releases_outlined, color: _kGold, size: 18),
      const SizedBox(width: 10),
      Text('$count new agent${count > 1 ? 's' : ''} discovered!',
          style: const TextStyle(color: _kGold, fontWeight: FontWeight.bold,
              fontSize: 13, letterSpacing: 0.5)),
    ]),
  );
}

class _EmptyAgentPlaceholder extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(vertical: 28),
    alignment: Alignment.center,
    child: Column(children: [
      Icon(Icons.hub_outlined,
          color: Colors.white.withValues(alpha: 0.1), size: 36),
      const SizedBox(height: 10),
      Text('Awaiting agent registry sync...',
          style: TextStyle(
              color: Colors.white.withValues(alpha: 0.18), fontSize: 12)),
    ]),
  );
}

class _ConnectionBadge extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ConnectionQuality>(
      valueListenable: ConnectionMonitor.instance.quality,
      builder: (_, q, __) {
        final (label, color) = switch (q) {
          ConnectionQuality.excellent => ('●  LIVE',    _kGreen),
          ConnectionQuality.good      => ('●  GOOD',    Colors.tealAccent),
          ConnectionQuality.degraded  => ('●  SLOW',    _kAmber),
          ConnectionQuality.offline   => ('○  OFFLINE', _kRed),
        };
        return Text(label,
            style: TextStyle(color: color, fontSize: 11,
                letterSpacing: 1.5, fontWeight: FontWeight.bold));
      },
    );
  }
}

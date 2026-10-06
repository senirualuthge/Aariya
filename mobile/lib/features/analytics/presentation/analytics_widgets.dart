part of 'analytics_screen.dart';

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

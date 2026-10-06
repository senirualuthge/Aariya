part of 'companion_screen.dart';

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

class _MiniTag extends StatelessWidget {
  final String label;
  final Color color;
  const _MiniTag(this.label, this.color);
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(7),
      border: Border.all(color: color.withValues(alpha: 0.35)),
    ),
    child: Text(label,
        style: TextStyle(color: color, fontSize: 9.5,
            letterSpacing: 0.7, fontWeight: FontWeight.w600)),
  );
}

class _ModeChip extends StatelessWidget {
  final String mode;
  const _ModeChip(this.mode);
  @override
  Widget build(BuildContext context) {
    final color = _modeColor(mode);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(mode,
          style: TextStyle(
            color: color, fontWeight: FontWeight.bold,
            fontSize: 11, letterSpacing: 2,
          )),
    );
  }
}

class _TraitChip extends StatelessWidget {
  final String label;
  final Color color;
  const _TraitChip({required this.label, required this.color});
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: color.withValues(alpha: 0.4)),
    ),
    child: Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 6, height: 6,
          decoration: BoxDecoration(
            color: color, shape: BoxShape.circle,
            boxShadow: [BoxShadow(color: color.withValues(alpha: 0.6), blurRadius: 5)],
          ),
        ),
        const SizedBox(width: 6),
        Text(label,
            style: TextStyle(color: color, fontSize: 10.5,
                fontWeight: FontWeight.w600)),
      ],
    ),
  );
}

/// Value-over-label stat box — shared with the chat presence sheet so both
/// surfaces render numeric readouts (voice / avatar / UI / health) identically.
class MiniStat extends StatelessWidget {
  final String label;
  final double value;
  final Color color;
  const MiniStat(this.label, this.value, this.color, {super.key});
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.08),
      borderRadius: BorderRadius.circular(9),
      border: Border.all(color: color.withValues(alpha: 0.22)),
    ),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(value.toStringAsFixed(2),
            style: TextStyle(
              color: color, fontWeight: FontWeight.bold,
              fontSize: 11.5, fontFamily: 'monospace',
            )),
        const SizedBox(height: 1),
        Text(label,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.3),
              fontSize: 8, letterSpacing: 1.2,
            )),
      ],
    ),
  );
}

/// Label + animated gradient bar — shared with the chat presence sheet so both
/// surfaces render latent / reviewer values identically.
class LatentBar extends StatelessWidget {
  final String label;
  final double value;
  final Color color;
  const LatentBar(
      {super.key, required this.label, required this.value, required this.color});
  @override
  Widget build(BuildContext context) {
    final v = value.clamp(0.0, 1.0);
    return Row(
      children: [
        SizedBox(
          width: 92,
          child: Text(label,
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.4),
                fontSize: 9.5, letterSpacing: 1,
              )),
        ),
        Expanded(
          child: TweenAnimationBuilder<double>(
            tween: Tween<double>(end: v),
            duration: _kAnim,
            curve: Curves.easeOutCubic,
            builder: (_, animated, __) => Container(
              height: 5,
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.06),
                borderRadius: BorderRadius.circular(4),
              ),
              child: FractionallySizedBox(
                alignment: Alignment.centerLeft,
                widthFactor: animated,
                child: Container(
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(4),
                    gradient: LinearGradient(
                      colors: [color.withValues(alpha: 0.6), color],
                    ),
                    boxShadow: [
                      BoxShadow(color: color.withValues(alpha: 0.4), blurRadius: 4),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
        SizedBox(
          width: 38,
          child: Text(
            '${(v * 100).toInt()}%',
            textAlign: TextAlign.right,
            style: TextStyle(
              color: color, fontSize: 9.5, fontFamily: 'monospace',
            ),
          ),
        ),
      ],
    );
  }
}

class _HealthBar extends StatelessWidget {
  final String label;
  final double value;
  final Color color;
  final String? trend;
  const _HealthBar({required this.label, required this.value, required this.color, this.trend});
  @override
  Widget build(BuildContext context) {
    final arrow = trend == 'rising'
        ? '▲'
        : trend == 'falling'
            ? '▼'
            : '●';
    final trendColor = trend == 'rising'
        ? _kGreen
        : trend == 'falling'
            ? _kRed
            : Colors.white38;
    return Row(
      children: [
        Expanded(
          child: LatentBar(label: label, value: value, color: color),
        ),
        const SizedBox(width: 8),
        Text(arrow, style: TextStyle(color: trendColor, fontSize: 10)),
      ],
    );
  }
}

class _FbButton extends StatelessWidget {
  final IconData icon;
  final String label;
  final Color color;
  final VoidCallback? onTap;
  const _FbButton({required this.icon, required this.label, required this.color, this.onTap});
  @override
  Widget build(BuildContext context) => Expanded(
    child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 9),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.1),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: color.withValues(alpha: 0.35)),
        ),
        child: Column(
          children: [
            Icon(icon, color: color, size: 17),
            const SizedBox(height: 3),
            Text(label,
                style: TextStyle(color: color, fontSize: 9.5,
                    letterSpacing: 0.6)),
          ],
        ),
      ),
    ),
  );
}

class _EmptyNote extends StatelessWidget {
  final String text;
  const _EmptyNote(this.text);
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 8),
    child: Text(text,
        style: TextStyle(
          color: Colors.white.withValues(alpha: 0.22), fontSize: 11,
        )),
  );
}

/// Live activity strip: the phone's slice of the real event-log ring.
///
/// Renders the same autonomy / governance / brain events the dashboard's
/// Event Log shows — fed by [CompanionScreen] from `GET /api/events/latest`
/// (which reads the signal bus's real ring), never synthetic data.
class ActivityStrip extends StatelessWidget {
  final List<Map<String, dynamic>> events;
  const ActivityStrip({super.key, required this.events});

  @override
  Widget build(BuildContext context) {
    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const _Label('RECENT ACTIVITY'),
              const Spacer(),
              Icon(Icons.bolt, color: _kGold.withValues(alpha: 0.7), size: 13),
              const SizedBox(width: 4),
              Text('live',
                  style: TextStyle(
                    color: _kGold.withValues(alpha: 0.7),
                    fontSize: 9, letterSpacing: 1.5,
                  )),
            ],
          ),
          const SizedBox(height: 6),
          if (events.isEmpty)
            const _EmptyNote('Waiting for real autonomy events…')
          else
            for (final e in events.take(_kMaxStripEvents)) _EventRow(event: e),
        ],
      ),
    );
  }
}

/// One real event-log entry: tag chip (dashboard color) + title + time.
class _EventRow extends StatelessWidget {
  final Map<String, dynamic> event;
  const _EventRow({required this.event});

  static String _fmtTime(dynamic ts) {
    if (ts is! num || ts <= 0) return '––:––';
    final dt = DateTime.fromMillisecondsSinceEpoch((ts * 1000).round()).toLocal();
    String two(int v) => v.toString().padLeft(2, '0');
    return '${two(dt.hour)}:${two(dt.minute)}:${two(dt.second)}';
  }

  @override
  Widget build(BuildContext context) {
    final tag = (event['tag'] as String? ?? 'SYSTEM').toUpperCase();
    final text = event['text'] as String? ?? '';
    final severity = (event['severity'] as String? ?? 'info').toLowerCase();
    final color = _tagColor(tag);
    final sevColor = severity == 'critical'
        ? _kRed
        : severity == 'warn'
            ? _kAmber
            : color;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 5),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2.5),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(6),
              border: Border.all(color: color.withValues(alpha: 0.4)),
            ),
            child: Text(tag,
                style: TextStyle(
                  color: color, fontSize: 8.5,
                  fontWeight: FontWeight.w800, letterSpacing: 1,
                )),
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Text(text,
                maxLines: 2, overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.72),
                  fontSize: 11.5, height: 1.3,
                )),
          ),
          const SizedBox(width: 8),
          // Severity dot + timestamp.
          Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Container(
                width: 6, height: 6,
                decoration: BoxDecoration(
                  color: sevColor, shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(color: sevColor.withValues(alpha: 0.6), blurRadius: 4),
                  ],
                ),
              ),
              const SizedBox(height: 3),
              Text(_fmtTime(event['ts']),
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.28),
                    fontSize: 9, fontFamily: 'monospace',
                  )),
            ],
          ),
        ],
      ),
    );
  }
}

class _ConnectionBadge extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ConnectionQuality>(
      valueListenable: ConnectionMonitor.instance.quality,
      builder: (_, q, __) {
        final (label, color) = switch (q) {
          ConnectionQuality.excellent => ('●  LIVE', _kGreen),
          ConnectionQuality.good      => ('●  GOOD', Colors.tealAccent),
          ConnectionQuality.degraded  => ('●  SLOW', _kAmber),
          ConnectionQuality.offline   => ('○  OFFLINE', _kRed),
        };
        return Text(label,
            style: TextStyle(color: color, fontSize: 11,
                letterSpacing: 1.5, fontWeight: FontWeight.bold));
      },
    );
  }
}

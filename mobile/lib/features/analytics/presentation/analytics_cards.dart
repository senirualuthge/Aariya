part of 'analytics_screen.dart';

extension _AnalyticsCardBuilders on _AnalyticsScreenState {
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

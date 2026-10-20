part of 'analytics_screen.dart';

extension _AnalyticsCardBuilders on _AnalyticsScreenState {
  // ── THIS DEVICE ────────────────────────────────────────────────────────────
  // The handset's own figures, sampled on-phone by [DeviceMetricsReporter].
  // Rendered ABOVE the brain's CPU/RAM cards because these answer the first
  // question in a lag report: is it the phone or the server?
  Widget _buildDeviceSection() {
    final deviceName = [_devManufacturer, _devModel]
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .join(' ');
    final hasSample = _battery != null || _devCpu != null || _devRam != null;

    final rightMeta = [
      if (_devOs.isNotEmpty) _devOs,
      if (_devRamTotalGb > 0)
        '${_devRamUsedGb.toStringAsFixed(1)}/${_devRamTotalGb.toStringAsFixed(1)} GB',
    ].join('  ·  ');

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const _Label('THIS DEVICE'),
              const SizedBox(width: 8),
              const _MiniTag('ON-PHONE', _kCyan),
              const Spacer(),
              if (deviceName.isNotEmpty)
                Flexible(
                  child: Text(
                    deviceName.toUpperCase(),
                    textAlign: TextAlign.right,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.45),
                      fontSize: 10,
                      letterSpacing: 1,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 12),
          if (!hasSample)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Text(
                'Collecting device stats…',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.25),
                  fontSize: 12,
                ),
              ),
            )
          else ...[
            Row(
              children: [
                Expanded(
                  child: _QuickStat(
                    label: 'BATTERY',
                    value: _battery == null ? '–' : '$_battery%',
                    color: _batteryColor(),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _QuickStat(
                    label: 'CPU',
                    value: _devCpu == null ? '–' : '${_devCpu!.toStringAsFixed(0)}%',
                    color: _devCpuColor(),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: _QuickStat(
                    label: 'RAM',
                    value: _devRam == null ? '–' : '${_devRam!.toStringAsFixed(0)}%',
                    color: _devRamColor(),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            // Battery bar — the one phone metric a number alone reads badly.
            TweenAnimationBuilder<double>(
              tween: Tween<double>(end: (_battery ?? 0) / 100),
              duration: _kAnim,
              curve: Curves.easeOutCubic,
              builder: (_, v, __) => ClipRRect(
                borderRadius: BorderRadius.circular(6),
                child: Container(
                  height: 6,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.07),
                    borderRadius: BorderRadius.circular(6),
                  ),
                  child: FractionallySizedBox(
                    alignment: Alignment.centerLeft,
                    widthFactor: v.clamp(0.0, 1.0),
                    child: Container(
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(6),
                        gradient: LinearGradient(colors: [
                          _batteryColor().withValues(alpha: 0.7),
                          _batteryColor(),
                        ]),
                        boxShadow: [
                          BoxShadow(
                            color: _batteryColor().withValues(alpha: 0.4),
                            blurRadius: 6,
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
            const SizedBox(height: 9),
            Row(
              children: [
                Icon(
                  _charging
                      ? Icons.battery_charging_full
                      : Icons.battery_5_bar_outlined,
                  size: 13,
                  color: _batteryColor().withValues(alpha: 0.85),
                ),
                const SizedBox(width: 5),
                Text(
                  _battery == null
                      ? 'Battery unavailable'
                      : '$_battery%  ·  ${_charging ? 'charging' : 'on battery'}',
                  style: TextStyle(
                    color: _batteryColor().withValues(alpha: 0.85),
                    fontSize: 10,
                    fontFamily: 'monospace',
                  ),
                ),
                const Spacer(),
                if (rightMeta.isNotEmpty)
                  Text(
                    rightMeta,
                    style: TextStyle(
                      color: Colors.white.withValues(alpha: 0.28),
                      fontSize: 10,
                      fontFamily: 'monospace',
                    ),
                  ),
              ],
            ),
            if (_devCpu == null || _devRam == null) ...[
              const SizedBox(height: 6),
              Text(
                // Say exactly which figure is missing and why it differs by
                // platform, instead of claiming RAM is absent while showing it.
                _devPlatform == 'android'
                    ? 'CPU usage is not exposed on this device.'
                    : 'CPU and RAM are only available on Android.',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.22),
                  fontSize: 9,
                ),
              ),
            ],
          ],
        ],
      ),
    );
  }

  Color _batteryColor() {
    final b = _battery;
    if (b == null) return Colors.white24;
    if (_charging) return _kGreen;
    return b <= 15 ? _kRed : b <= 35 ? _kAmber : _kGreen;
  }

  Color _devCpuColor() {
    final x = _devCpu;
    if (x == null) return Colors.white24;
    return x > 85 ? _kRed : x > 60 ? _kAmber : _kCyan;
  }

  Color _devRamColor() {
    final x = _devRam;
    if (x == null) return Colors.white24;
    return x > 90 ? _kRed : x > 70 ? _kAmber : const Color(0xFF00BFA5);
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

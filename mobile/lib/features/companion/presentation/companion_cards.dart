part of 'companion_screen.dart';

extension _CompanionCardBuilders on _CompanionScreenState {
  // ── Trait Activation Engine ───────────────────────────────────────────────

  Widget _buildTraitCard(Map<String, dynamic> bundle, String mode, bool hasTrait) {
    final traits = bundle['active_traits'];
    final idleTraits = bundle['traits']; // daemon idle frame sends ids only
    final latent = _trait['latent'];
    final voice = bundle['voice'];
    final avatar = bundle['avatar'];
    final ui = bundle['ui'];
    final arbitration = _trait['arbitration'];

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              _Label('TRAIT ACTIVATION ENGINE'),
              Spacer(),
              _MiniTag('MAX 3', _kTeal),
            ],
          ),
          const SizedBox(height: 10),
          if (!hasTrait)
            const _EmptyNote('Awaiting first brain turn…')
          else ...[
            if (traits is List && traits.isNotEmpty) ...[
              Wrap(
                spacing: 8, runSpacing: 8,
                children: [
                  for (final t in traits.take(3))
                    _TraitChip(
                      label: '${t['label'] ?? ''}',
                      color: _hexColor('${t['color'] ?? ''}'),
                    ),
                ],
              ),
            ] else if (idleTraits is List && idleTraits.isNotEmpty) ...[
              Wrap(
                spacing: 8, runSpacing: 8,
                children: [
                  for (final id in idleTraits.take(3))
                    _TraitChip(label: '$id', color: _kPurple),
                ],
              ),
              Text(
                'idle presence ($mode)',
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.28), fontSize: 10,
                ),
              ),
            ],
            if (arbitration is List && arbitration.isNotEmpty) ...[
              const SizedBox(height: 12),
              const _Label('ARBITRATION'),
              const SizedBox(height: 6),
              // Situational swaps with humanized ids — the replaced bank trait
              // struck through, exactly like the dashboard presence panel.
              for (final a in arbitration)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('⇢ ',
                          style: TextStyle(
                              color: _kAmber.withValues(alpha: 0.9),
                              fontSize: 10.5)),
                      Expanded(
                        child: Text.rich(
                          TextSpan(
                            style: TextStyle(
                              color: Colors.white.withValues(alpha: 0.55),
                              fontSize: 10.5, height: 1.3,
                            ),
                            children: [
                              TextSpan(
                                text: humanizeTraitId('${a['trait'] ?? ''}'),
                                style: TextStyle(
                                  color: _kAmber.withValues(alpha: 0.95),
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              const TextSpan(text: '  in for  '),
                              TextSpan(
                                text: humanizeTraitId('${a['replaced'] ?? ''}'),
                                style: const TextStyle(
                                  decoration: TextDecoration.lineThrough,
                                  color: Colors.white38,
                                ),
                              ),
                              TextSpan(text: ' — ${a['reason'] ?? ''}'),
                            ],
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
            ],
            if (latent is Map && latent.isNotEmpty) ...[
              const SizedBox(height: 14),
              const _Label('LATENT STATE'),
              const SizedBox(height: 8),
              for (final (key, label, color) in kLatentKeys)
                Padding(
                  padding: const EdgeInsets.only(bottom: 6),
                  child: LatentBar(
                    label: label,
                    value: _num(latent[key]),
                    color: color,
                  ),
                ),
            ],
            if (voice is Map && voice.isNotEmpty) ...[
              const SizedBox(height: 14),
              const _Label('VOICE'),
              const SizedBox(height: 8),
              Row(
                children: [
                  MiniStat('RATE', _num(voice['speech_rate'], 1.0), _kCyan),
                  const SizedBox(width: 8),
                  MiniStat('PITCH', _num(voice['pitch'], 1.0), _kGreen),
                  const SizedBox(width: 8),
                  MiniStat('VOL', _num(voice['volume'], 0.8), _kBlue),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '${voice['pauses'] ?? ''}',
                      maxLines: 2, overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.4),
                        fontSize: 10, fontStyle: FontStyle.italic,
                      ),
                    ),
                  ),
                ],
              ),
            ],
            if (avatar is Map && avatar.isNotEmpty) ...[
              const SizedBox(height: 14),
              const _Label('AVATAR'),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8, runSpacing: 8,
                children: [
                  MiniStat('SMILE', _num(avatar['Smile']), const Color(0xFFff8fa3)),
                  MiniStat('TILT', _num(avatar['HeadTilt']), _kGold),
                  MiniStat('FOCUS', _num(avatar['EyeFocus']), _kCyan),
                  MiniStat('POSTURE', _num(avatar['Posture']), _kBlue),
                  MiniStat('BLINK', _num(avatar['BlinkRate']), _kTeal),
                  MiniStat('MICRO', _num(avatar['MicroMovement']), _kPurple),
                ],
              ),
            ],
            if (ui is Map && ui.isNotEmpty) ...[
              const SizedBox(height: 14),
              const _Label('UI'),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8, runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  MiniStat('PROGRESS', _num(ui['progress_bar']), _kCyan),
                  _MiniTag(
                    ui['highlighted_suggestions'] == true
                        ? 'SUGGESTIONS ✓'
                        : 'SUGGESTIONS —',
                    _kBlue,
                  ),
                  _MiniTag(
                    ui['monitoring_status'] == true
                        ? 'MONITOR ●'
                        : 'MONITOR ○',
                    _kTeal,
                  ),
                  MiniStat('UI TONE', _num(ui['color_tone']), _kPurple),
                ],
              ),
            ],
          ],
        ],
      ),
    );
  }

  // ── Transparency Satisfaction ─────────────────────────────────────────────

  Widget _buildTransparencyCard() {
    final sat = _num(_transp['transparency_satisfaction'], 0.5).clamp(0.0, 1.0);
    final dialBack = _transp['dial_back'] == true;
    final redline = _transp['redline'] == true;
    final reason = _transp['reason'] as String? ?? '';
    final count = (_transp['feedback_count'] as num?)?.toInt() ?? 0;
    final explicit = _transp['explicit_rating'];
    final implicit = _transp['implicit_rating'];
    final hasRatings = explicit != null || implicit != null;
    // Gate the gauge on REAL data — never render a fabricated reading.
    final hasData = _transp.isNotEmpty;

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const _Label('TRANSPARENCY SATISFACTION'),
              const Spacer(),
              _MiniTag('$count FEEDBACK', _kBlue),
            ],
          ),
          if (hasData) ...[
            const SizedBox(height: 12),
            Row(
              children: [
              // Gauge — real satisfaction %
              TweenAnimationBuilder<double>(
                tween: Tween<double>(end: sat),
                duration: _kAnim,
                curve: Curves.easeOutCubic,
                builder: (_, v, __) => SizedBox(
                  width: 72, height: 72,
                  child: Stack(
                    alignment: Alignment.center,
                    children: [
                      SizedBox(
                        width: 72, height: 72,
                        child: CircularProgressIndicator(
                          value: 1.0,
                          strokeWidth: 6,
                          color: Colors.white.withValues(alpha: 0.06),
                        ),
                      ),
                      SizedBox(
                        width: 72, height: 72,
                        child: CircularProgressIndicator(
                          value: v,
                          strokeWidth: 6,
                          backgroundColor: Colors.transparent,
                          valueColor: AlwaysStoppedAnimation<Color>(
                            dialBack ? _kRed : _kCyan,
                          ),
                        ),
                      ),
                      Text(
                        '${(v * 100).toInt()}%',
                        style: const TextStyle(
                          color: Colors.white,
                          fontWeight: FontWeight.bold,
                          fontSize: 17,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      dialBack
                          ? 'DIALED BACK'
                          : sat >= 0.7
                              ? 'CLEAR'
                              : sat >= 0.4
                                  ? 'MIXED'
                                  : 'STRAINED',
                      style: TextStyle(
                        color: dialBack
                            ? _kRed
                            : sat >= 0.7
                                ? _kGreen
                                : sat >= 0.4
                                    ? _kAmber
                                    : _kRed,
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        letterSpacing: 2,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      reason.isEmpty ? 'No red-line — satisfaction within range' : reason,
                      style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.5),
                        fontSize: 11, height: 1.35,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
          // Explicit vs implicit rating split — the compute() fields the
          // dashboard presence panel shows (honest '—' before any feedback).
          if (hasRatings) ...[
            const SizedBox(height: 10),
            Row(
              children: [
                Text('explicit',
                    style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.4),
                        fontSize: 10)),
                const SizedBox(width: 5),
                Text(
                  explicit is num
                      ? explicit.toDouble().toStringAsFixed(2)
                      : '—',
                  style: const TextStyle(
                    color: _kGreen, fontSize: 10,
                    fontFamily: 'monospace', fontWeight: FontWeight.bold,
                  ),
                ),
                const SizedBox(width: 16),
                Text('implicit',
                    style: TextStyle(
                        color: Colors.white.withValues(alpha: 0.4),
                        fontSize: 10)),
                const SizedBox(width: 5),
                Text(
                  implicit is num
                      ? implicit.toDouble().toStringAsFixed(2)
                      : '—',
                  style: const TextStyle(
                    color: _kCyan, fontSize: 10,
                    fontFamily: 'monospace', fontWeight: FontWeight.bold,
                  ),
                ),
                const Spacer(),
              ],
            ),
          ],
            const SizedBox(height: 14),
          ],
          if (dialBack)
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: _kRed.withValues(alpha: 0.1),
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: _kRed.withValues(alpha: 0.45)),
              ),
              child: Row(
                children: [
                  const Icon(Icons.healing_outlined, color: _kRed, size: 18),
                  const SizedBox(width: 10),
                  Expanded(
                    child: Text(
                      redline
                          ? 'Red-line active — she is dialing back intensity '
                              'until you say it\'s fine.'
                          : 'Dialed back — she is lowering intensity '
                              'until you say it\'s fine.',
                      style: const TextStyle(
                          color: Color(0xFFffb3b3), fontSize: 11.5, height: 1.35),
                    ),
                  ),
                  TextButton(
                    onPressed: _fbState == 'sending'
                        ? null
                        : () => _postFeedback(clear: true),
                    style: TextButton.styleFrom(foregroundColor: _kGreen),
                    child: const Text('It\'s fine now', style: TextStyle(fontSize: 11.5)),
                  ),
                ],
              ),
            )
          else ...[
            if (!hasData) ...[
              const SizedBox(height: 8),
              const _EmptyNote('Awaiting transparency reading…'),
            ],
            const Text('Was that clear?',
                style: TextStyle(
                  color: Color(0x59FFFFFF),
                  fontSize: 10, letterSpacing: 1.5,
                )),
            const SizedBox(height: 8),
            Row(
              children: [
                _FbButton(
                  icon: Icons.sentiment_dissatisfied,
                  label: 'unclear',
                  color: _kRed,
                  onTap: _fbState == 'sending'
                      ? null
                      : () => _postFeedback(rating: 0.2, discomfort: true),
                ),
                const SizedBox(width: 8),
                _FbButton(
                  icon: Icons.sentiment_neutral,
                  label: 'mostly',
                  color: _kAmber,
                  onTap: _fbState == 'sending'
                      ? null
                      : () => _postFeedback(rating: 0.5),
                ),
                const SizedBox(width: 8),
                _FbButton(
                  icon: Icons.sentiment_satisfied,
                  label: 'clear',
                  color: _kGreen,
                  onTap: _fbState == 'sending'
                      ? null
                      : () => _postFeedback(rating: 0.8),
                ),
              ],
            ),
          ],
          if (_fbState == 'done') ...[
            const SizedBox(height: 10),
            const Text('Feedback recorded — thank you',
                style: TextStyle(color: _kGreen, fontSize: 11)),
          ] else if (_fbState == 'error') ...[
            const SizedBox(height: 10),
            const Text('Could not reach Aariya — try again',
                style: TextStyle(color: _kRed, fontSize: 11)),
          ],
        ],
      ),
    );
  }

  // ── Companion health (stability / attachment / reviewer) ──────────────────

  Widget _buildHealthCard() {
    final stability = _num(_health['stability_index']).clamp(0.0, 1.0);
    final attachRisk = _num(_health['over_attachment_risk']).clamp(0.0, 1.0);
    final trust = _trust.clamp(0.0, 1.0);
    final reliance = (_health['reliance_signals'] as num?)?.toInt() ?? 0;
    final absent = _num(_health['absent_days']);
    final reviewer = _health['reviewer'];
    final trend = _health['trend'];

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const _Label('RELATIONSHIP HEALTH'),
          const SizedBox(height: 12),
          _HealthBar(
            label: 'STABILITY INDEX',
            value: stability,
            color: stability >= 0.7 ? _kGreen : stability >= 0.4 ? _kAmber : _kRed,
            trend: trend is Map ? trend['stability_index'] as String? : null,
          ),
          const SizedBox(height: 10),
          _HealthBar(
            label: 'OVER-ATTACHMENT RISK',
            value: attachRisk,
            color: attachRisk >= 0.6 ? _kRed : attachRisk >= 0.3 ? _kAmber : _kTeal,
            trend: trend is Map ? trend['over_attachment_risk'] as String? : null,
          ),
          const SizedBox(height: 10),
          _HealthBar(
            label: 'TRUST',
            value: trust,
            color: _kBlue,
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              MiniStat('RELIANCE', reliance.toDouble(), _kGold),
              const SizedBox(width: 8),
              MiniStat('ABSENT', absent, _kPurple),
            ],
          ),
          if (reviewer is Map && reviewer.isNotEmpty) ...[
            const SizedBox(height: 14),
            const _Label('REVIEWER'),
            const SizedBox(height: 8),
            for (final (key, label) in [
              ('tone_appropriateness', 'TONE'),
              ('boundary_respect', 'BOUNDARIES'),
              ('engagement', 'ENGAGEMENT'),
              ('reassurance', 'REASSURANCE'),
            ])
              Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: LatentBar(
                  label: label,
                  value: _num(reviewer[key]),
                  color: _kBlue,
                ),
              ),
          ],
          if (_health.isEmpty)
            const _EmptyNote('Awaiting health snapshots…'),
        ],
      ),
    );
  }
}

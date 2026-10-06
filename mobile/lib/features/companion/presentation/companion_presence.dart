import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../../../core/services/server_config.dart';
import '../../../core/state/brain_state_controller.dart';
import 'companion_screen.dart';

// ── Palette (matches the app's dark theme) ───────────────────────────────────
const _kSurface = Color(0xFF110F1E);
const _kCyan    = Color(0xFF00E5FF);
const _kGreen   = Color(0xFF2ecc71);
const _kBlue    = Color(0xFF4a9eff);
const _kPurple  = Color(0xFFb44fff);
const _kRed     = Color(0xFFE74C5E);
const _kAmber   = Color(0xFFFF9800);
const _kTeal    = Color(0xFF00BFA5);

/// Behavior-mode accent colors — shared by the chip and the summary sheet so
/// the phone renders the same mode language everywhere.
Color modeColor(String mode) => switch (mode.toUpperCase()) {
  'COMBAT'  => _kRed,
  'STEALTH' => _kPurple,
  _         => _kGreen,
};

/// Compact presence pill for the chat app bar.
///
/// Shows Aariya's real behavior mode + active-trait count from the live
/// synoptic (parsed by [BrainStateController]); tapping opens the
/// [CompanionPresenceSheet] summary. Nothing here is fabricated — when no
/// synoptic has arrived yet it renders a neutral awaiting state.
class CompanionPresenceChip extends StatelessWidget {
  final BrainStateController controller;

  const CompanionPresenceChip({super.key, required this.controller});

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        final mode = controller.behaviorMode;
        final traits = controller.activeTraits;
        final hasData = mode.isNotEmpty;
        // Awaiting state is NEUTRAL — never green, which would imply CALM.
        final color = hasData ? modeColor(mode) : Colors.white38;

        return InkWell(
          borderRadius: BorderRadius.circular(18),
          onTap: () => CompanionPresenceSheet.show(context, controller),
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: color.withValues(alpha: 0.45)),
            ),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 7, height: 7,
                  decoration: BoxDecoration(
                    color: color, shape: BoxShape.circle,
                    boxShadow: [
                      BoxShadow(color: color.withValues(alpha: 0.4), blurRadius: 5),
                    ],
                  ),
                ),
                const SizedBox(width: 6),
                Text(
                  hasData ? '$mode · ${traits.length}' : '···',
                  style: TextStyle(
                    color: color,
                    fontSize: 10.5,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 0.8,
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

/// Bottom-sheet summary of the Companion data, opened from the chat app bar.
///
/// Shows the real trait engine (mode, active traits, voice), transparency
/// satisfaction and relationship health. Prefers the freshest synoptic in
/// [BrainStateController]; refreshes transparency + health over REST
/// (`GET /api/compliance/health`) so the summary stays live even between
/// turns. Missing server data renders honest empty states — never synthetic.
class CompanionPresenceSheet extends StatefulWidget {
  final BrainStateController controller;

  const CompanionPresenceSheet({super.key, required this.controller});

  static void show(BuildContext context, BrainStateController controller) {
    showModalBottomSheet(
      context: context,
      backgroundColor: _kSurface,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (_) => CompanionPresenceSheet(controller: controller),
    );
  }

  @override
  State<CompanionPresenceSheet> createState() => _CompanionPresenceSheetState();
}

class _CompanionPresenceSheetState extends State<CompanionPresenceSheet> {
  Map<String, dynamic> _health = {}; // REST health snapshot (latest)
  Map<String, dynamic> _transp = {}; // REST transparency

  @override
  void initState() {
    super.initState();
    _fetchHealth();
  }

  Future<void> _fetchHealth() async {
    try {
      final uri = Uri.parse(
        '${ServerConfig.instance.httpBase}/api/compliance/health?user_id=user_default');
      final res = await http.get(uri).timeout(const Duration(seconds: 6));
      if (res.statusCode != 200 || !mounted) return;
      final body = jsonDecode(res.body);
      if (body is! Map) return;
      final parsed = parseHealthBody(body);
      setState(() {
        _health = parsed['health'] ?? const {};
        _transp = parsed['transparency'] ?? const {};
      });
    } catch (_) {
      // Offline — the sheet keeps showing the synoptic data already present.
    }
  }

  @override
  Widget build(BuildContext context) {
    final syn = widget.controller.synoptic;
    final mode = widget.controller.behaviorMode;
    final traits = widget.controller.activeTraits;

    // Transparency: REST refresh wins, else the synoptic's per-turn value.
    final satisfaction =
        ((_transp['transparency_satisfaction'] as num?)?.toDouble() ??
                widget.controller.transparencySatisfaction)
            .clamp(0.0, 1.0);
    final synTransparency = syn['transparency'];
    final dialBack = (_transp['dial_back'] == true) ||
        (synTransparency is Map && synTransparency['dial_back'] == true);
    final stability =
        ((_health['stability_index'] as num?)?.toDouble() ?? 0.5)
            .clamp(0.0, 1.0);
    final attachRisk =
        ((_health['over_attachment_risk'] as num?)?.toDouble() ?? 0.0)
            .clamp(0.0, 1.0);
    // Trust: the persisted health snapshot refreshes over REST while idle,
    // so the bar stays live between turns (controller.trust only moves on
    // live state.update frames — the REST snapshot is the fresher source).
    final trust =
        ((_health['trust'] as num?)?.toDouble() ?? widget.controller.trust)
            .clamp(0.0, 1.0);

    final te = syn['trait_engine'];
    final voice = te is Map ? te['voice'] : null;
    // Dashboard parity: the real latent bars, arbitration swaps and UI
    // parameter readout all travel inside the same trait_engine bundle.
    final latent = te is Map ? te['latent'] : null;
    final arbitration = te is Map ? te['arbitration'] : null;
    final ui = te is Map ? te['ui'] : null;

    return SafeArea(
      child: ConstrainedBox(
        constraints: BoxConstraints(
          maxHeight: MediaQuery.of(context).size.height * 0.75,
        ),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
            Row(
              children: [
                const Icon(Icons.favorite_outline, color: _kCyan, size: 16),
                const SizedBox(width: 8),
                const Text('AARIYA · PRESENCE',
                    style: TextStyle(
                      color: _kCyan, fontWeight: FontWeight.bold,
                      fontSize: 12, letterSpacing: 2,
                    )),
                const Spacer(),
                _ModeChip(mode),
              ],
            ),
            const SizedBox(height: 14),
            if (traits.isNotEmpty) ...[
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
              const SizedBox(height: 14),
            ] else
              Text('Awaiting first brain turn…',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.25), fontSize: 11,
                  )),
            if (arbitration is List && arbitration.isNotEmpty) ...[
              const _Label('ARBITRATION'),
              const SizedBox(height: 6),
              // Situational swaps — humanized ids, replaced bank trait struck
              // through, exactly like the full Companion screen / web panel.
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
              const SizedBox(height: 14),
            ],
            if (latent is Map && latent.isNotEmpty) ...[
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
              const SizedBox(height: 14),
            ],
            if (voice is Map && voice.isNotEmpty) ...[
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
              const SizedBox(height: 14),
            ],
            if (ui is Map && ui.isNotEmpty) ...[
              const _Label('UI'),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8, runSpacing: 8,
                crossAxisAlignment: WrapCrossAlignment.center,
                children: [
                  MiniStat('PROGRESS', _num(ui['progress_bar']), _kCyan),
                  _Pill(
                    ui['highlighted_suggestions'] == true
                        ? 'SUGGESTIONS ✓'
                        : 'SUGGESTIONS —',
                    _kBlue,
                  ),
                  _Pill(
                    ui['monitoring_status'] == true ? 'MONITOR ●' : 'MONITOR ○',
                    _kTeal,
                  ),
                  MiniStat('UI TONE', _num(ui['color_tone']), _kPurple),
                ],
              ),
              const SizedBox(height: 14),
            ],
            // Transparency satisfaction gauge.
            Row(
              children: [
                const _Label('TRANSPARENCY'),
                const Spacer(),
                Text('${(satisfaction * 100).toInt()}%',
                    style: TextStyle(
                      color: dialBack ? _kRed : _kCyan,
                      fontWeight: FontWeight.bold, fontSize: 13,
                      fontFamily: 'monospace',
                    )),
              ],
            ),
            const SizedBox(height: 6),
            _Bar(value: satisfaction, color: dialBack ? _kRed : _kCyan),
            if (dialBack) ...[
              const SizedBox(height: 6),
              Text('Dialed back — she is lowering intensity until you say it\'s fine',
                  style: TextStyle(color: _kRed.withValues(alpha: 0.9), fontSize: 10.5)),
            ],
            const SizedBox(height: 14),
            Row(
              children: [
                const _Label('STABILITY INDEX'),
                const Spacer(),
                Text('${(stability * 100).toInt()}%',
                    style: TextStyle(
                      color: stability >= 0.7 ? _kGreen : stability >= 0.4 ? _kAmber : _kRed,
                      fontWeight: FontWeight.bold, fontSize: 13,
                      fontFamily: 'monospace',
                    )),
              ],
            ),
            const SizedBox(height: 6),
            _Bar(value: stability,
                color: stability >= 0.7 ? _kGreen : stability >= 0.4 ? _kAmber : _kRed),
            const SizedBox(height: 14),
            Row(
              children: [
                const _Label('OVER-ATTACHMENT RISK'),
                const Spacer(),
                Text('${(attachRisk * 100).toInt()}%',
                    style: TextStyle(
                      color: attachRisk >= 0.6 ? _kRed : attachRisk >= 0.3 ? _kAmber : _kTeal,
                      fontWeight: FontWeight.bold, fontSize: 13,
                      fontFamily: 'monospace',
                    )),
              ],
            ),
            const SizedBox(height: 6),
            _Bar(value: attachRisk,
                color: attachRisk >= 0.6 ? _kRed : attachRisk >= 0.3 ? _kAmber : _kTeal),
            const SizedBox(height: 14),
            Row(
              children: [
                const _Label('TRUST'),
                const Spacer(),
                Text('${(trust * 100).toInt()}%',
                    style: const TextStyle(
                      color: _kBlue, fontWeight: FontWeight.bold, fontSize: 13,
                      fontFamily: 'monospace',
                    )),
              ],
            ),
              const SizedBox(height: 6),
              _Bar(value: trust, color: _kBlue),
              const SizedBox(height: 6),
              Text('full Companion view · bottom nav',
                  style: TextStyle(
                    color: Colors.white.withValues(alpha: 0.2), fontSize: 9.5,
                  )),
            ],
          ),
        ),
      ),
    );
  }
}

// ── Shared primitives ─────────────────────────────────────────────────────────

Color _hexColor(String hex) {
  final cleaned = hex.replaceFirst('#', '');
  final value = int.tryParse(cleaned, radix: 16);
  return value == null ? _kCyan : Color(0xFF000000 | value);
}

double _num(dynamic v, [double d = 0.0]) =>
    v is num ? v.toDouble() : (v is String ? double.tryParse(v) ?? d : d);

class _ModeChip extends StatelessWidget {
  final String mode;
  const _ModeChip(this.mode);
  @override
  Widget build(BuildContext context) {
    final hasData = mode.isNotEmpty;
    final color = modeColor(mode);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.14),
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: color.withValues(alpha: 0.5)),
      ),
      child: Text(hasData ? mode : '···',
          style: TextStyle(
            color: hasData ? color : Colors.white38,
            fontWeight: FontWeight.bold, fontSize: 10.5, letterSpacing: 1.5,
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
    padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 4),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(9),
      border: Border.all(color: color.withValues(alpha: 0.4)),
    ),
    child: Text(label,
        style: TextStyle(color: color, fontSize: 10,
            fontWeight: FontWeight.w600)),
  );
}

class _Label extends StatelessWidget {
  final String text;
  const _Label(this.text);
  @override
  Widget build(BuildContext context) => Text(text,
      style: TextStyle(
        color: Colors.white.withValues(alpha: 0.32), fontSize: 10,
        letterSpacing: 1.8, fontWeight: FontWeight.w600,
      ));
}

class _Pill extends StatelessWidget {
  final String label;
  final Color color;
  const _Pill(this.label, this.color);
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
    decoration: BoxDecoration(
      color: color.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(7),
      border: Border.all(color: color.withValues(alpha: 0.35)),
    ),
    child: Text(label,
        style: TextStyle(
          color: color, fontSize: 9.5,
          letterSpacing: 0.7, fontWeight: FontWeight.w600,
        )),
  );
}

class _Bar extends StatelessWidget {
  final double value;
  final Color color;
  const _Bar({required this.value, required this.color});
  @override
  Widget build(BuildContext context) => Container(
    height: 5,
    decoration: BoxDecoration(
      color: Colors.white.withValues(alpha: 0.07),
      borderRadius: BorderRadius.circular(4),
    ),
    child: FractionallySizedBox(
      alignment: Alignment.centerLeft,
      widthFactor: value.clamp(0.0, 1.0),
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(4),
          gradient: LinearGradient(colors: [color.withValues(alpha: 0.6), color]),
        ),
      ),
    ),
  );
}

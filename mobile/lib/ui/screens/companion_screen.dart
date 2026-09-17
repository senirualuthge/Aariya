import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../../services/connection_monitor.dart';
import '../../services/server_config.dart';
import '../../services/websocket_service.dart';

// ── Palette (matches the analytics screen's dark observability theme) ─────────
const _kBackground = Color(0xFF0A0812);
const _kSurface    = Color(0xFF110F1E);
const _kCyan       = Color(0xFF00E5FF);
const _kGreen      = Color(0xFF2ecc71);
const _kBlue       = Color(0xFF4a9eff);
const _kPurple     = Color(0xFFb44fff);
const _kGold       = Color(0xFFffc800);
const _kRed        = Color(0xFFE74C5E);
const _kAmber      = Color(0xFFFF9800);
const _kTeal       = Color(0xFF00BFA5);

const _kUser = 'user_default';
const _kAnim = Duration(milliseconds: 700);
const _kMaxStripEvents = 5;

/// Autonomy + governance event tags the Companion strip shows (the user asked
/// for autonomy/governance activity specifically — the endpoint supports any
/// source filter, and the phone asks for exactly these).
const _kStripSources = 'DAEMON,PLANNER,LEARNING,MODEL,EVOLUTION,GOVERNANCE';

/// Event-tag colors — match the web dashboard's LOG_TAG_COLOR exactly so the
/// phone and laptop render the same activity with the same chip language.
const Map<String, Color> _kTagColors = {
  'DAEMON':    Color(0xFFffd93d),
  'PLANNER':   Color(0xFFa78bfa),
  'LEARNING':  Color(0xFF34d399),
  'MODEL':     Color(0xFF6bcbef),
  'BRAIN':     Color(0xFFff8fa3),
  'MOBILE':    Color(0xFF00e5ff),
  'HEALTH':    Color(0xFFfb923c),
  'GOVERNANCE': Color(0xFFa3e635),
  'FUNCTIONS': Color(0xFFe879f9),
  'EVOLUTION': Color(0xFFf59e0b),
  'SYSTEM':    Color(0xFF94a3b8),
};

Color _tagColor(String tag) => _kTagColors[tag] ?? _kCyan;

/// The 7 canonical latent-state keys (doc state_keys) + display labels.
/// Shared with the chat presence sheet (companion_presence.dart) so both
/// surfaces render the same latent bars from the same palette.
const List<(String, String, Color)> kLatentKeys = [
  ('focus_level',       'FOCUS',       _kCyan),
  ('urgency_level',     'URGENCY',     _kAmber),
  ('empathy_level',     'EMPATHY',     _kGreen),
  ('confidence_level',  'CONFIDENCE',  _kBlue),
  ('cognitive_load',    'LOAD',        _kPurple),
  ('engagement_level',  'ENGAGEMENT',  _kGold),
  ('system_stability',  'STABILITY',   _kTeal),
];

/// Behavior-mode accent colors (server sends mode name, not a color).
Color _modeColor(String mode) => switch (mode) {
  'COMBAT'  => _kRed,
  'STEALTH' => _kPurple,
  _         => _kGreen,
};

/// Parses server hex trait colors like "#00f2ff".
Color _hexColor(String hex) {
  final cleaned = hex.replaceFirst('#', '');
  final value = int.tryParse(cleaned, radix: 16);
  return value == null ? _kCyan : Color(0xFF000000 | value);
}

/// "sardonic_wit" → "Sardonic Wit" — used for arbitration ids (the replaced
/// bank trait is not in active_traits, so no label is available server-side).
/// Shared with the chat presence sheet (companion_presence.dart) so both
/// surfaces render swap ids the same way.
String humanizeTraitId(String id) {
  if (id.isEmpty) return id;
  return id.split('_').where((w) => w.isNotEmpty)
      .map((w) => w[0].toUpperCase() + w.substring(1))
      .join(' ');
}

double _num(dynamic v, [double d = 0.0]) =>
    v is num ? v.toDouble() : (v is String ? double.tryParse(v) ?? d : d);

/// A trait bundle only counts as meaningful once it carries real measured
/// state. The singleton's `bundle()` always returns the 7-key shape (with
/// empty latent + empty traits before the first brain turn), so key-count
/// checks like `isNotEmpty` would adopt a misleading empty CALM bundle and
/// wipe fresher WS data. Gate on content instead.
bool _isMeaningfulTrait(Map<String, dynamic> trait) {
  final latent = trait['latent'];
  final active = trait['active_traits'];
  return (latent is Map && latent.isNotEmpty) ||
      (active is List && active.isNotEmpty);
}

/// Parses a `/api/compliance/health` response body into the live maps the
/// Companion screen renders. Pure + testable (no HTTP here).
///
/// The endpoint now carries `trait_engine` (the last REAL brain turn's trait
/// bundle) alongside the persisted health + transparency snapshots, so the
/// phone can refresh trait data over REST while idle — not just from
/// `state.update` frames.
/// Shared by the Companion screen, the chat presence sheet and tests.
Map<String, Map<String, dynamic>> parseHealthBody(Map<dynamic, dynamic> body) => {
  'health': body['latest'] is Map
      ? Map<String, dynamic>.from(body['latest'] as Map)
      : const <String, dynamic>{},
  'transparency': body['transparency'] is Map
      ? Map<String, dynamic>.from(body['transparency'] as Map)
      : const <String, dynamic>{},
  'trait_engine': body['trait_engine'] is Map
      ? Map<String, dynamic>.from(body['trait_engine'] as Map)
      : const <String, dynamic>{},
};

/// Companion governance view — the phone shows the same real Trait Activation
/// Engine + Transparency Satisfaction + Relationship Health as the dashboard.
///
/// Data is NEVER fabricated locally:
///  * `state.update` frames on the chat channel carry the full synoptic
///    (trait_engine bundle, transparency, companion_health, behavior_mode,
///    emotion_reason) computed by the last real brain turn.
///  * `avatar.update` broadcasts keep the trait readouts live between turns
///    (idle presence resolved by the 24/7 autonomy daemon).
///  * `GET /api/compliance/health` polls persisted transparency + health
///    snapshots AND the last real trait-engine bundle, so the panel has data
///    (including latent bars / voice / avatar) even before the first mobile
///    turn and refreshes it while idle.
class CompanionScreen extends StatefulWidget {
  const CompanionScreen({super.key});

  @override
  State<CompanionScreen> createState() => _CompanionScreenState();
}

class _CompanionScreenState extends State<CompanionScreen> {
  // ── Live state (all real, from the server) ────────────────────────────────
  Map<String, dynamic> _trait      = {}; // full trait bundle (state.update)
  Map<String, dynamic> _transp     = {}; // transparency compute()
  Map<String, dynamic> _health     = {}; // companion_health snapshot
  Map<String, dynamic> _mode       = {}; // behavior_mode
  Map<String, dynamic> _emotionRsn = {}; // emotion_reason
  Map<String, dynamic> _idle       = {}; // avatar.update idle presence
  List<Map<String, dynamic>> _events = []; // real event-log ring (REST poll)
  double _trust = 0.5; // top-level trust from the last state.update frame

  String _fbState = 'idle'; // idle | sending | done | error
  Timer? _fbResetTimer;      // pending "reset to idle" timer (cancelled on dispose)
  StreamSubscription<Map<String, dynamic>>? _sub;
  Timer? _pollTimer;

  @override
  void initState() {
    super.initState();
    // Live channel: state.update (full synoptic) + avatar.update (idle).
    _sub = WebSocketService.instance.messagesStream.listen(_onFrame);
    // REST fallbacks so transparency/health/activity render before the first
    // frame — real persisted values, never synthetic.
    _pollHealth();
    _pollEvents();
    _pollTimer = Timer.periodic(const Duration(seconds: 8), (_) {
      _pollHealth();
      _pollEvents();
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    _pollTimer?.cancel();
    _fbResetTimer?.cancel();
    super.dispose();
  }

  // ── Frame intake ──────────────────────────────────────────────────────────

  void _onFrame(Map<String, dynamic> data) {
    if (!mounted) return;
    switch (data['type']) {
      case 'state.update':
        final state = data['state'];
        if (state is Map) {
          final syn = state['synoptic'];
          if (syn is Map) {
            setState(() {
              _trait  = _map(syn['trait_engine']);
              _transp = _map(syn['transparency']);
              _health = _map(syn['companion_health']);
              _mode   = _map(syn['behavior_mode']);
              _emotionRsn = _map(syn['emotion_reason']);
              // Top-level trust travels with the frame, not inside synoptic.
              final t = state['trust'];
              if (t is num) _trust = t.toDouble().clamp(0.0, 1.0);
              // A fresh real turn supersedes any cached idle presence.
              _idle = const {};
            });
          }
        }
      case 'avatar.update':
        // Idle presence between turns — real values from the daemon. Used as
        // the live bundle only when no fresher turn bundle exists (a
        // state.update clears it above).
        setState(() {
          _idle = Map<String, dynamic>.from(data);
        });
    }
  }

  Map<String, dynamic> _map(dynamic v) =>
      v is Map ? Map<String, dynamic>.from(v) : const {};

  // ── REST: persisted health snapshot (real, never synthetic) ───────────────

  Future<void> _pollHealth() async {
    try {
      final uri = Uri.parse(
        '${ServerConfig.instance.httpBase}/api/compliance/health?user_id=$_kUser');
      final res = await http.get(uri).timeout(const Duration(seconds: 6));
      if (res.statusCode != 200 || !mounted) return;
      final body = jsonDecode(res.body);
      if (body is! Map) return;
      final parsed = parseHealthBody(body);        setState(() {
          _health = parsed['health'] ?? const {};
          _transp = parsed['transparency'] ?? const {};
          // Trust is persisted in the health snapshot (the brain writes it
          // into the ring every real turn) — feed it through so the Trust
          // bar stays live over REST while idle, not just from state.update
          // frames. Only adopted when the snapshot actually carries a value.
          final persistedTrust = _health['trust'];
          if (persistedTrust is num) {
            _trust = persistedTrust.toDouble().clamp(0.0, 1.0);
          }
          // Trait bundle from the last real brain turn — keeps latent bars /
          // voice / avatar readouts live over REST while idle. Only adopted
          // when it actually carries measured state (empty-at-boot bundles
          // must not wipe fresher state.update data).
          final trait = parsed['trait_engine'];
          if (trait != null && _isMeaningfulTrait(trait)) _trait = trait;
        });
    } catch (_) {
      // Offline / server busy — keep showing the last real values.
    }
  }

  // ── REST: real event-log ring (same source the dashboard Event Log uses) ─

  Future<void> _pollEvents() async {
    try {
      final uri = Uri.parse(
        '${ServerConfig.instance.httpBase}/api/events/latest'
        '?limit=$_kMaxStripEvents&sources=$_kStripSources');
      final res = await http.get(uri).timeout(const Duration(seconds: 6));
      if (res.statusCode != 200 || !mounted) return;
      final body = jsonDecode(res.body);
      if (body is Map && body['events'] is List) {
        setState(() {
          _events = (body['events'] as List)
              .whereType<Map>()
              .map((e) => Map<String, dynamic>.from(e))
              .toList();
        });
      }
    } catch (_) {
      // Offline / server busy — keep showing the last real events.
    }
  }

  // ── Transparency feedback (mirrors the dashboard's exact contract) ────────

  Future<void> _postFeedback({
    double? rating,
    bool discomfort = false,
    bool clear = false,
  }) async {
    setState(() => _fbState = 'sending');
    try {
      final uri = Uri.parse(
        '${ServerConfig.instance.httpBase}/api/compliance/feedback');
      final res = await http.post(
        uri,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'user_id': _kUser,
          if (clear) 'action': 'clear' else 'rating': rating,
          if (!clear) 'discomfort': discomfort,
        }),
      ).timeout(const Duration(seconds: 8));
      if (res.statusCode != 200) {
        if (mounted) setState(() => _fbState = 'error');
        return;
      }
      final body = jsonDecode(res.body);
      if (body is Map && body['transparency'] is Map) {
        setState(() {
          _transp = Map<String, dynamic>.from(body['transparency'] as Map);
          _fbState = 'done';
        });
      } else {
        if (mounted) setState(() => _fbState = 'error');
        return;
      }
      await _pollHealth();
      _fbResetTimer?.cancel();
      _fbResetTimer = Timer(const Duration(seconds: 3), () {
        if (mounted) setState(() => _fbState = 'idle');
      });
    } catch (_) {
      if (mounted) setState(() => _fbState = 'error');
    }
  }

  // ── UI ────────────────────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    // Coherent bundle source: live idle presence (daemon) wins while present
    // — otherwise the last real turn bundle (WS or REST). The mode chip,
    // trait chips and voice/avatar readouts all read the SAME source so the
    // card can't show e.g. a CALM chip beside STEALTH idle traits.
    final usingIdle = _idle.isNotEmpty;
    final bundle = usingIdle ? _idle : _trait;
    final mode = (bundle['mode'] as String?) ??
        (_mode['mode'] as String?) ??
        '—';
    final hasTrait = bundle.isNotEmpty;

    return Scaffold(
      backgroundColor: _kBackground,
      body: Column(
        children: [
          _buildHeader(),
          Expanded(
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 36),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildModeCard(mode),
                  const SizedBox(height: 12),
                  _buildActivityStrip(),
                  const SizedBox(height: 12),
                  _buildTraitCard(bundle, mode, hasTrait),
                  const SizedBox(height: 12),
                  _buildTransparencyCard(),
                  const SizedBox(height: 12),
                  _buildHealthCard(),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

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
          const Icon(Icons.favorite_outline, color: _kCyan, size: 18),
          const SizedBox(width: 10),
          const Text('COMPANION',
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

  // ── Live activity strip (real autonomy / governance events) ───────────────

  Widget _buildActivityStrip() => ActivityStrip(events: _events);

  // ── Behavior mode + explainable emotion ───────────────────────────────────

  Widget _buildModeCard(String mode) {
    final reasons = _mode['reasons'];
    final directive = _mode['directive'] as String?;
    final er = _emotionRsn;
    final drivers = er['drivers'];
    final emotionLabel = er['label'] as String?;

    return _Card(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const _Label('BEHAVIOR MODE'),
              const Spacer(),
              _ModeChip(mode),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              MiniStat('FOCUS', _num(_map(_trait['latent'])['focus_level'],
                  _num(_mode['focus_level'])), _kCyan),
              const SizedBox(width: 8),
              MiniStat('URGENCY', _num(_map(_trait['latent'])['urgency_level'],
                  _num(_mode['urgency_level'])), _kAmber),
            ],
          ),
          if (directive != null && directive.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(directive,
                style: TextStyle(
                  color: Colors.white.withValues(alpha: 0.45), fontSize: 11,
                  height: 1.35, fontStyle: FontStyle.italic,
                )),
          ],
          if (reasons is List && reasons.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6, runSpacing: 6,
              children: [
                for (final r in reasons.take(3))
                  _MiniTag('$r', Colors.white54),
              ],
            ),
          ],
          if (emotionLabel != null) ...[
            const SizedBox(height: 14),
            Row(
              children: [
                const _Label('WHY SHE REACTED'),
                const Spacer(),
                _MiniTag(emotionLabel, _kGold),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              er['reasoning'] as String? ?? er['hedged'] as String? ?? '',
              style: TextStyle(
                color: Colors.white.withValues(alpha: 0.55),
                fontSize: 12, height: 1.4,
              ),
            ),
            if (drivers is List && drivers.isNotEmpty) ...[
              const SizedBox(height: 8),
              Wrap(
                spacing: 6, runSpacing: 6,
                children: [
                  for (final d in drivers.take(4))
                    _MiniTag(
                      '${d['signal']} ${(d['value'] as num?)?.toDouble() ?? 0}',
                      _kBlue,
                    ),
                ],
              ),
            ],
          ],
        ],
      ),
    );
  }

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

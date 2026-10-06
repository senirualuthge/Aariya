import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;

import '../../../core/services/connection_monitor.dart';
import '../../../core/services/server_config.dart';
import '../../../core/services/websocket_service.dart';

part 'companion_cards.dart';
part 'companion_primitives.dart';

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

}


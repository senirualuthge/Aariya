import 'package:aariya_mobile/services/websocket_service.dart';
import 'package:aariya_mobile/ui/screens/companion_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Real event payloads exactly as `/api/events/latest` returns them (which
/// mirror what the dashboard's Event Log derives from each signal).
List<Map<String, dynamic>> _sampleEvents() => [
  {
    'id': 'sig_ab12',
    'ts': 1786329000.0,
    'tag': 'GOVERNANCE',
    'text': 'Age policy set to 18+',
    'severity': 'warn',
  },
  {
    'id': 'sig_cd34',
    'ts': 1786328900.0,
    'tag': 'PLANNER',
    'text': 'New goal: write more tests',
    'severity': 'info',
  },
  {
    'id': 'sig_ef56',
    'ts': 1786328800.0,
    'tag': 'DAEMON',
    'text': 'Presence mode → STEALTH — quiet presence',
    'severity': 'warn',
  },
];

/// Drives the REAL server frame path: frames are emitted through the shared
/// WebSocketService stream (exactly as they arrive on /ws/mobile), so the
/// screen renders the actual payload shapes — never test-local fixtures of a
/// different contract.
void main() {
  group('parseHealthBody', () {
    test('extracts health, transparency AND trait_engine from the REST body',
        () {
      final parsed = parseHealthBody({
        'latest': {
          'stability_index': 0.74,
          'over_attachment_risk': 0.31,
          'trust': 0.66, // persisted per-turn by the brain's health snapshots
        },
        'trend': {'stability_index': 'rising'},
        'history': <Map<String, dynamic>>[],
        'transparency': {
          'transparency_satisfaction': 0.82,
          'dial_back': false,
        },
        'trait_engine': {
          'mode': 'CALM',
          'latent': {'focus_level': 0.8, 'urgency_level': 0.2},
          'active_traits': [
            {'id': 'assertive_efficiency', 'label': 'Assertive Efficiency',
             'color': '#00f2ff'},
          ],
          'voice': {'speech_rate': 1.02},
          'avatar': {'Smile': 0.7},
          'ui': {'color_tone': 0.8},
        },
      });

      expect(parsed['health']!['stability_index'], 0.74);
      // Trust rides along in the persisted snapshot — the Companion screen
      // feeds it into the Trust bar so it stays live over REST while idle.
      expect(parsed['health']!['trust'], 0.66);
      expect(parsed['transparency']!['transparency_satisfaction'], 0.82);
      // This is the new capability: trait data refreshes over REST while idle.
      final trait = parsed['trait_engine']!;
      expect(trait['mode'], 'CALM');
      expect(trait['latent']!['focus_level'], 0.8);
      expect((trait['active_traits'] as List).single['label'],
          'Assertive Efficiency');
      expect(trait['voice']!['speech_rate'], 1.02);
    });

    test('missing sections degrade to empty maps (never throw)', () {
      final parsed = parseHealthBody({'transparency': {'dial_back': true}});
      expect(parsed['health'], isEmpty);
      expect(parsed['transparency']!['dial_back'], isTrue);
      expect(parsed['trait_engine'], isEmpty);
    });
  });

  testWidgets('state.update frame renders real trait engine + transparency',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: CompanionScreen()));

    WebSocketService.instance.emitTestFrame({
      'type': 'state.update',
      'state': {
        'trust': 0.78,
        'synoptic': {
          'trait_engine': {
            'mode': 'CALM',
            'latent': {
              'focus_level': 0.8,
              'urgency_level': 0.2,
              'empathy_level': 0.7,
              'confidence_level': 0.9,
              'cognitive_load': 0.3,
              'engagement_level': 0.6,
              'system_stability': 0.9,
            },
            'active_traits': [
              {'id': 'assertive_efficiency', 'label': 'Assertive Efficiency', 'color': '#00f2ff'},
              {'id': 'predictive_initiative', 'label': 'Predictive Initiative', 'color': '#6bcbef'},
              {'id': 'empathetic_calibration', 'label': 'Empathetic Calibration', 'color': '#a8e6cf'},
            ],
            'arbitration': [
              {'trait': 'sardonic_wit', 'replaced': 'assertive_efficiency',
               'reason': 'user is playful — sardonic wit'},
            ],
            'voice': {'speech_rate': 1.02, 'pitch': 0.98, 'volume': 1.0,
                      'pauses': '150 ms pause before punchline'},
            'avatar': {'Smile': 0.7, 'HeadTilt': 1.5, 'EyeFocus': 0.8,
                       'Posture': 0.9, 'BlinkRate': 0.2, 'MicroMovement': 0.0},
            'ui': {'progress_bar': 0.3, 'highlighted_suggestions': true,
                   'monitoring_status': false, 'color_tone': 0.8},
          },            'transparency': {
            'transparency_satisfaction': 0.82,
            'explicit_rating': 0.83,
            'implicit_rating': 0.61,
            'dial_back': false,
            'reason': 'no red-line — satisfaction within range',
            'feedback_count': 3,
          },
          'companion_health': {
            'stability_index': 0.74,
            'over_attachment_risk': 0.31,
            'reliance_signals': 2,
            'absent_days': 0.4,
            'reviewer': {
              'tone_appropriateness': 0.78,
              'boundary_respect': 0.85,
              'engagement': 0.66,
              'reassurance': 0.61,
            },
            'trend': {'stability_index': 'rising', 'over_attachment_risk': 'stable'},
          },
          'behavior_mode': {
            'mode': 'CALM',
            'focus_level': 0.8,
            'urgency_level': 0.2,
            'reasons': ['baseline valence=0.10'],
            'directive': 'Warm, steady, open presence',
          },
          'emotion_reason': {
            'label': 'WARM',
            'reasoning': 'I picked up on the user emotion (0.65) leaving me warm '
                         '(valence 0.40, arousal 0.30).',
            'drivers': [
              {'signal': 'user_emotion', 'value': 0.65},
              {'signal': 'trust', 'value': 0.75},
            ],
          },
        },
      },
    });
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 800));

    // Behavior mode + emotion reason (real values from the frame).
    expect(find.text('CALM'), findsWidgets);
    expect(find.textContaining('WARM'), findsWidgets);
    expect(find.textContaining('picked up on the user emotion'),
        findsOneWidget);

    // Trait engine: the 3 active traits from the server bundle.
    expect(find.text('Assertive Efficiency'), findsOneWidget);
    expect(find.text('Predictive Initiative'), findsOneWidget);
    expect(find.text('Empathetic Calibration'), findsOneWidget);
    // Arbitration swap reason — humanized ids, rich text.
    expect(find.textContaining('Sardonic Wit'), findsOneWidget);
    expect(find.textContaining('in for'), findsOneWidget);
    expect(find.textContaining('user is playful'), findsOneWidget);
    // Latent bars (FOCUS also appears as the mode-card stat, so findsWidgets).
    expect(find.text('FOCUS'), findsWidgets);
    expect(find.text('URGENCY'), findsWidgets);
    expect(find.text('EMPATHY'), findsOneWidget);
    expect(find.text('CONFIDENCE'), findsOneWidget);
    expect(find.text('STABILITY'), findsWidgets);
    // Voice + avatar readouts.
    expect(find.textContaining('punchline'), findsOneWidget);
    expect(find.text('SMILE'), findsOneWidget);
    // UI parameter readout (dashboard parity).
    expect(find.text('PROGRESS'), findsOneWidget);
    expect(find.text('SUGGESTIONS ✓'), findsOneWidget);
    expect(find.text('MONITOR ○'), findsOneWidget);
    expect(find.text('UI TONE'), findsOneWidget);

    // Transparency gauge at 82%.
    expect(find.text('82%'), findsOneWidget);
    expect(find.text('CLEAR'), findsOneWidget);
    // Explicit / implicit rating split (real compute() fields).
    expect(find.text('explicit'), findsOneWidget);
    expect(find.text('0.83'), findsOneWidget);
    expect(find.text('implicit'), findsOneWidget);
    expect(find.text('0.61'), findsOneWidget);
    // Trust bar in relationship health (top-level frame trust).
    expect(find.text('TRUST'), findsOneWidget);
    expect(find.text('unclear'), findsOneWidget);
    expect(find.text('mostly'), findsOneWidget);
    expect(find.text('clear'), findsWidgets);

    // Companion health reviewer scores.
    expect(find.text('STABILITY INDEX'), findsOneWidget);
    expect(find.text('OVER-ATTACHMENT RISK'), findsOneWidget);
    expect(find.text('TONE'), findsOneWidget);
    expect(find.text('REASSURANCE'), findsOneWidget);
  });

  testWidgets('dial-back red-line shows the banner + resume action',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: CompanionScreen()));

    WebSocketService.instance.emitTestFrame({
      'type': 'state.update',
      'state': {
        'synoptic': {
          'transparency': {
            'transparency_satisfaction': 0.2,
            'dial_back': true,
            'redline': true,
            'reason': 'user reported emotional discomfort — dialed back (red-line)',
            'feedback_count': 1,
          },
        },
      },
    });
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 800));

    expect(find.text('DIALED BACK'), findsOneWidget);
    expect(find.textContaining('dialing back intensity'), findsOneWidget);
    // The red-line replaces the plain feedback buttons with the resume action.
    expect(find.text("It's fine now"), findsOneWidget);
    expect(find.text('unclear'), findsNothing);
  });

  testWidgets('activity strip renders real events from the event-log ring',
      (tester) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(body: ActivityStrip(events: _sampleEvents())),
    ));
    await tester.pump();

    // Tag chips (real dashboard colors), titles, and timestamps.
    expect(find.text('GOVERNANCE'), findsOneWidget);
    expect(find.text('PLANNER'), findsOneWidget);
    expect(find.text('DAEMON'), findsOneWidget);
    expect(find.text('Age policy set to 18+'), findsOneWidget);
    expect(find.text('New goal: write more tests'), findsOneWidget);
    expect(find.textContaining('STEALTH'), findsOneWidget);
  });

  testWidgets('activity strip empty state waits for real events',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: Scaffold(body: ActivityStrip(events: []))),
    );
    await tester.pump();
    expect(find.text('Waiting for real autonomy events…'), findsOneWidget);
  });

  testWidgets('idle avatar.update frame keeps the trait view live',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(home: CompanionScreen()));

    // Daemon idle presence broadcast (between turns).
    WebSocketService.instance.emitTestFrame({
      'type': 'avatar.update',
      'mode': 'STEALTH',
      'traits': ['hyper_intellectual_curiosity', 'strategic_silence', 'persistent_presence'],
      'voice': {'speech_rate': 0.9, 'pitch': 1.0, 'volume': 0.85,
                'pauses': 'knows when not to talk — silent until spoken to'},
      'avatar': {'Smile': 0.1, 'HeadTilt': -2.0, 'EyeFocus': 0.5,
                 'Posture': 0.7, 'BlinkRate': 0.3, 'MicroMovement': 0.0},
    });
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 800));

    expect(find.text('STEALTH'), findsWidgets);
    expect(find.textContaining('idle presence'), findsOneWidget);
    expect(find.text('persistent_presence'), findsOneWidget);
    expect(find.textContaining('silent until spoken to'), findsOneWidget);
  });
}

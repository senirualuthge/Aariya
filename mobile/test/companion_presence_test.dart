import 'package:aariya_mobile/state/brain_state_controller.dart';
import 'package:aariya_mobile/ui/widgets/companion_presence.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Real `state.update` synoptic shape (exactly what /ws/mobile carries after a
/// brain turn) so the parsing tests drive genuine server payloads.
Map<String, dynamic> _synopticFrame() => {
  'type': 'state.update',
  'state': {
    'trust': 0.78,
    'emotion': 'joy',
    'synoptic': {
      'trait_engine': {
        'mode': 'CALM',
        'active_traits': [
          {'id': 'assertive_efficiency', 'label': 'Assertive Efficiency', 'color': '#00f2ff'},
          {'id': 'predictive_initiative', 'label': 'Predictive Initiative', 'color': '#6bcbef'},
          {'id': 'empathetic_calibration', 'label': 'Empathetic Calibration', 'color': '#a8e6cf'},
        ],
        'latent': {
          'focus_level': 0.8,
          'urgency_level': 0.2,
          'empathy_level': 0.7,
          'confidence_level': 0.9,
          'cognitive_load': 0.3,
          'engagement_level': 0.6,
          'system_stability': 0.9,
        },
        'voice': {'speech_rate': 1.02, 'pitch': 0.98, 'volume': 1.0,
                  'pauses': 'short pauses'},
        'arbitration': [
          {'trait': 'sardonic_wit', 'replaced': 'assertive_efficiency',
           'reason': 'user is playful — sardonic wit'},
        ],
        'ui': {'progress_bar': 0.3, 'highlighted_suggestions': true,
               'monitoring_status': false, 'color_tone': 0.8},
      },
      'behavior_mode': {'mode': 'CALM'},
      'transparency': {
        'transparency_satisfaction': 0.82,
        'dial_back': false,
      },
    },
  },
};

void main() {
  group('BrainStateController synoptic parsing', () {
    test('parses mode, active traits and transparency from state.update', () {
      final brain = BrainStateController();
      brain.updateFromServer(_synopticFrame());

      expect(brain.behaviorMode, 'CALM');
      expect(brain.activeTraits.length, 3);
      expect(brain.activeTraits.first['label'], 'Assertive Efficiency');
      expect(brain.transparencySatisfaction, closeTo(0.82, 0.001));
      brain.dispose();
    });

    test('empty synoptic degrades to neutral getters', () {
      final brain = BrainStateController();
      brain.updateFromServer({'type': 'state.update', 'state': {'trust': 0.5}});
      expect(brain.behaviorMode, '');
      expect(brain.activeTraits, isEmpty);
      expect(brain.transparencySatisfaction, 0.5);
      brain.dispose();
    });

    test('mode falls back to behavior_mode when trait_engine missing', () {
      final brain = BrainStateController();
      brain.updateFromServer({
        'type': 'state.update',
        'state': {
          'synoptic': {
            'behavior_mode': {'mode': 'STEALTH'},
          },
        },
      });
      expect(brain.behaviorMode, 'STEALTH');
      brain.dispose();
    });
  });

  group('CompanionPresenceChip', () {
    testWidgets('renders mode + trait count and opens the summary sheet',
        (tester) async {
      final brain = BrainStateController();
      brain.updateFromServer(_synopticFrame());
      addTearDown(brain.dispose);

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Align(
            alignment: Alignment.topRight,
            child: CompanionPresenceChip(controller: brain),
          ),
        ),
      ));

      // Compact pill: CALM · 3.
      expect(find.text('CALM · 3'), findsOneWidget);

      // Tap opens the presence summary sheet with real data.
      await tester.tap(find.byType(CompanionPresenceChip));
      await tester.pumpAndSettle();

      expect(find.text('AARIYA · PRESENCE'), findsOneWidget);
      expect(find.text('Assertive Efficiency'), findsOneWidget);
      expect(find.text('Predictive Initiative'), findsOneWidget);
      // Arbitration reasoning (dashboard parity — humanized ids, reason).
      expect(find.text('ARBITRATION'), findsOneWidget);
      expect(find.textContaining('Sardonic Wit'), findsOneWidget);
      expect(find.textContaining('user is playful'), findsOneWidget);
      // UI parameter readout (dashboard parity).
      expect(find.text('UI'), findsOneWidget);
      expect(find.text('PROGRESS'), findsOneWidget);
      expect(find.text('SUGGESTIONS ✓'), findsOneWidget);
      expect(find.text('MONITOR ○'), findsOneWidget);
      expect(find.text('UI TONE'), findsOneWidget);
      // Voice readout (dashboard parity — shared MiniStat stats).
      expect(find.text('VOICE'), findsOneWidget);
      expect(find.text('RATE'), findsOneWidget);
      expect(find.text('PITCH'), findsOneWidget);
      expect(find.text('VOL'), findsOneWidget);
      expect(find.textContaining('short pauses'), findsOneWidget);
      // Latent state bars (dashboard parity — shared LatentBar + kLatentKeys).
      expect(find.text('LATENT STATE'), findsOneWidget);
      expect(find.text('FOCUS'), findsOneWidget);
      expect(find.text('URGENCY'), findsOneWidget);
      expect(find.text('EMPATHY'), findsOneWidget);
      expect(find.text('CONFIDENCE'), findsOneWidget);
      expect(find.text('LOAD'), findsOneWidget);
      expect(find.text('ENGAGEMENT'), findsOneWidget);
      expect(find.text('STABILITY'), findsOneWidget);
      expect(find.text('TRANSPARENCY'), findsOneWidget);
      expect(find.text('82%'), findsOneWidget);
    });

    testWidgets('awaiting state renders a neutral placeholder', (tester) async {
      final brain = BrainStateController();
      addTearDown(brain.dispose);

      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: CompanionPresenceChip(controller: brain)),
      ));

      expect(find.text('···'), findsWidgets);
    });
  });
}

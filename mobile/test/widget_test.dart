import 'package:aariya_mobile/core/state/brain_state_controller.dart';
import 'package:aariya_mobile/features/voice/widgets/animated_text_stream.dart';
import 'package:aariya_mobile/features/voice/widgets/voice_reactive_orb.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('BrainStateController', () {
    test('starts at neutral defaults', () {
      final brain = BrainStateController();
      expect(brain.trust, 0.5);
      expect(brain.activeMode, 'balanced');
      expect(brain.isThinking, isFalse);
      expect(brain.isSpeaking, isFalse);
      expect(brain.isListening, isFalse);
      expect(brain.emotion, 'neutral');
      brain.dispose();
    });

    test('updateFromServer applies the state.update envelope', () {
      final brain = BrainStateController();
      brain.updateFromServer({
        'type': 'state.update',
        'state': {
          'valence': 0.8,
          'arousal': 0.6,
          'trust': 0.75,
          'current_mode': 'focus',
          'emotion': 'joy',
        },
      });
      expect(brain.trust, 0.75);
      expect(brain.valence, 0.8);
      expect(brain.arousal, 0.6);
      expect(brain.activeMode, 'focus');
      expect(brain.emotionValence, 0.8);
      expect(brain.emotionArousal, 0.6);
      brain.dispose();
    });

    test('updateFromMap maps emotion label to valence/arousal', () {
      final brain = BrainStateController();
      brain.updateFromMap({'emotion': 'sadness', 'trust': 0.2});
      expect(brain.emotion, 'sadness');
      expect(brain.emotionValence, -0.8);
      expect(brain.emotionArousal, 0.2);
      brain.dispose();
    });

    test('transient flags and energy pulse notify listeners', () {
      final brain = BrainStateController();
      var notifications = 0;
      brain.addListener(() => notifications++);

      brain.setThinking(true);
      brain.setSpeaking(true);
      brain.setListening(false);
      brain.pulseEnergy(0.9);
      expect(brain.isThinking, isTrue);
      expect(brain.isSpeaking, isTrue);
      expect(brain.isListening, isFalse);
      expect(brain.energy, 0.9);
      expect(notifications, greaterThan(0));

      brain.reset();
      expect(brain.isThinking, isFalse);
      expect(brain.isSpeaking, isFalse);
      expect(brain.isListening, isFalse);
      brain.dispose();
    });
  });

  group('AnimatedTextStream', () {
    testWidgets('renders text with a streaming cursor', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: AnimatedTextStream(text: 'Hello Aariya', isStreaming: true),
          ),
        ),
      );
      expect(
        find.textContaining('Hello Aariya', findRichText: true),
        findsOneWidget,
      );
    });

    testWidgets('renders text without a cursor when not streaming',
        (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: AnimatedTextStream(text: 'Calm', isStreaming: false),
          ),
        ),
      );
      expect(find.text('Calm', findRichText: true), findsOneWidget);
    });
  });

  group('VoiceReactiveOrb', () {
    testWidgets('renders at idle and reacts to a voice level', (tester) async {
      await tester.pumpWidget(
        const MaterialApp(
          home: Scaffold(
            body: Center(
              child: VoiceReactiveOrb(level: 0.8, size: 220),
            ),
          ),
        ),
      );
      await tester.pump(const Duration(milliseconds: 100));
      expect(find.byType(VoiceReactiveOrb), findsOneWidget);
      await tester.pump(const Duration(milliseconds: 500));
      expect(tester.takeException(), isNull);
    });
  });
}

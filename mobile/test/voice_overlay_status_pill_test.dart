import 'package:aariya_mobile/ui/widgets/companion_presence.dart';
import 'package:aariya_mobile/ui/widgets/voice_conversation_overlay.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('statusPillColor — in sync with the presence chip', () {
    test('CALM mode tints every state green (same helper as the chip)', () {
      for (final state in VoiceState.values) {
        expect(
          statusPillColor(state, 'CALM'),
          modeColor('CALM'),
          reason: 'pill for $state must equal the chip color for CALM',
        );
        expect(statusPillColor(state, 'CALM'), const Color(0xFF2ecc71));
      }
    });

    test('STEALTH mode tints every state purple (same helper as the chip)', () {
      for (final state in VoiceState.values) {
        expect(statusPillColor(state, 'STEALTH'), modeColor('STEALTH'));
        expect(statusPillColor(state, 'STEALTH'), const Color(0xFFb44fff));
      }
    });

    test('COMBAT mode tints every state red (same helper as the chip)', () {
      for (final state in VoiceState.values) {
        expect(statusPillColor(state, 'COMBAT'), modeColor('COMBAT'));
        expect(statusPillColor(state, 'COMBAT'), const Color(0xFFE74C5E));
      }
    });

    test('no mode yet → honest state-accent fallback, never a mode color', () {
      expect(statusPillColor(VoiceState.listening, ''),
          Colors.greenAccent);
      expect(statusPillColor(VoiceState.processing, ''),
          Colors.orangeAccent);
      expect(statusPillColor(VoiceState.speaking, ''),
          const Color(0xFF3BAFDA));
      // Lowercase / unknown input still maps through modeColor's default.
      expect(statusPillColor(VoiceState.speaking, 'calm'),
          modeColor('CALM'));
    });
  });
}

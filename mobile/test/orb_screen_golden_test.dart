import 'package:aariya_mobile/features/voice/widgets/voice_reactive_orb.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Golden screenshot tests for the orb's visual design.
///
/// Renders [VoiceReactiveOrb] in its three signature states and locks the
/// pixels with `matchesGoldenFile`, so a regression in the particle shell,
/// glow core, or theme colors fails CI instead of silently changing.
///
/// WHY THE GOLDENS ARE STABLE ACROSS PLATFORMS:
///   - The orb is a pure [CustomPainter]: no text, so no font/anti-alias
///     variance; flutter_test always rasterizes through the headless software
///     renderer regardless of host OS.
///   - All randomness is seeded (Random(42)/Random(7) at library load), so
///     every frame is deterministic given the pump schedule below.
///   - Goldens are generated with the SAME pinned Flutter SDK used by CI
///     (3.41.9) — same engine version ⇒ same rasterization.
///
/// If the orb's rendering intentionally changes, regenerate with:
///   flutter test --update-goldens mobile/test/orb_screen_golden_test.dart
void main() {
  const double orbSize = 300;

  // Fixed pump schedule — the orb runs a repeating 60 s animation controller,
  // so pumpAndSettle() would never settle. Fixed durations make the captured
  // frame deterministic (controller value = elapsed/60000 under the test
  // binding's virtual clock, independent of runner load).
  //
  // NOTE: the level smoother converges exponentially, so the goldens lock a
  // CONVERGING (mid-attack) state, not a steady state. That is deterministic,
  // but a change to the smoothing constants will shift the goldens — bump them
  // deliberately with --update-goldens.
  Future<void> pumpOrb(WidgetTester tester, VoiceReactiveOrb orb) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          backgroundColor: const Color(0xFF0B0B14),
          body: Center(
            child: RepaintBoundary(
              child: SizedBox.square(
                dimension: orbSize,
                child: orb,
              ),
            ),
          ),
        ),
      ),
    );
    // Let the level smoother converge toward target, then a final frame.
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump(const Duration(milliseconds: 1200));
    await tester.pump(const Duration(milliseconds: 500));
    await tester.pump(const Duration(milliseconds: 100));
    // A paint-time exception could still rasterize a plausible-looking frame;
    // surface it explicitly so it can't masquerade as a changed golden.
    expect(tester.takeException(), isNull);
  }

  testWidgets('cosmic theme at idle (orb_screen_idle_cosmic)', (tester) async {
    await pumpOrb(tester, const VoiceReactiveOrb(size: orbSize, level: 0));
    await expectLater(
      find.byType(VoiceReactiveOrb),
      matchesGoldenFile('goldens/orb_screen_idle_cosmic.png'),
    );
  });

  testWidgets('ember theme at idle (orb_screen_ember)', (tester) async {
    await pumpOrb(
      tester,
      VoiceReactiveOrb(
        size: orbSize,
        level: 0,
        theme: VoiceReactiveOrb.themeNamed('ember'),
      ),
    );
    await expectLater(
      find.byType(VoiceReactiveOrb),
      matchesGoldenFile('goldens/orb_screen_ember.png'),
    );
  });

  testWidgets('cosmic theme, high energy (orb_screen_joy_active)',
      (tester) async {
    await pumpOrb(
      tester,
      const VoiceReactiveOrb(
        size: orbSize,
        level: 0.85,
        bandMid: 0.6,
        bandHigh: 0.4,
      ),
    );
    await expectLater(
      find.byType(VoiceReactiveOrb),
      matchesGoldenFile('goldens/orb_screen_joy_active.png'),
    );
  });
}

import 'dart:math' as math;
import 'package:aariya_mobile/core/audio_analyser.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  const sampleRate = 44100;

  List<double> tone(double freq, double amplitude, int n) =>
      List<double>.generate(
        n,
        (i) => amplitude * math.sin(2 * math.pi * freq * i / sampleRate),
      );

  final analyzer = PcmAnalyzer(fftSize: 1024);

  group('PcmAnalyzer', () {
    test('silence yields near-zero energy everywhere', () {
      final levels = analyzer.analyze(List.filled(1024, 0.0));
      expect(levels.overall, lessThan(0.001));
      expect(levels.low, lessThan(0.001));
      expect(levels.mid, lessThan(0.001));
      expect(levels.high, lessThan(0.001));
    });

    test('200 Hz tone lands in the low band', () {
      final levels = analyzer.analyze(tone(200, 1.0, 1024));
      expect(levels.low, greaterThan(levels.mid));
      expect(levels.low, greaterThan(levels.high));
      expect(levels.low, greaterThan(0.0));
    });

    test('5 kHz tone lands in the mid band', () {
      final levels = analyzer.analyze(tone(5000, 1.0, 1024));
      expect(levels.mid, greaterThan(levels.low));
      expect(levels.mid, greaterThan(levels.high));
      expect(levels.mid, greaterThan(0.0));
    });

    test('20 kHz tone lands in the high band', () {
      final levels = analyzer.analyze(tone(20000, 1.0, 1024));
      expect(levels.high, greaterThan(levels.mid));
      expect(levels.high, greaterThan(levels.low));
    });

    test('overall volume scales with amplitude', () {
      final quiet = analyzer.analyze(tone(5000, 0.1, 1024));
      final loud = analyzer.analyze(tone(5000, 1.0, 1024));
      expect(quiet.overall, greaterThan(0.0));
      expect(quiet.overall, lessThan(loud.overall));
    });

    test('sensitivity boosts all channels', () {
      final base = analyzer.analyze(tone(5000, 0.1, 1024));
      final boosted =
          analyzer.analyze(tone(5000, 0.1, 1024), sensitivity: 3.0);
      expect(boosted.overall, greaterThan(base.overall));
      expect(boosted.mid, greaterThan(base.mid));
    });
  });

  group('PcmAnalyzer.spectrum', () {
    test('produces the configured number of bars in [0, 1]', () {
      final levels = analyzer.analyze(tone(1000, 1.0, 1024));
      expect(levels.spectrum.length, 16);
      for (final bar in levels.spectrum) {
        expect(bar, inInclusiveRange(0.0, 1.0));
      }
    });

    test('silence yields a flat, near-zero spectrum', () {
      final levels = analyzer.analyze(List.filled(1024, 0.0));
      for (final bar in levels.spectrum) {
        expect(bar, lessThan(0.001));
      }
    });

    test('a 1 kHz tone lights the low bars and leaves the top dark', () {
      // bin(1000 Hz) ≈ 23 → quadratic-spaced bar 3 (bins 18–32).
      final levels = analyzer.analyze(tone(1000, 1.0, 1024));
      expect(levels.spectrum[3], greaterThan(levels.spectrum[10]));
      expect(levels.spectrum[3], greaterThan(0.0));
      // High bars are essentially silent.
      for (var i = 10; i < levels.spectrum.length; i++) {
        expect(levels.spectrum[i], lessThan(levels.spectrum[3] / 4 + 0.01));
      }
    });

    test('a 20 kHz tone lights the top bar and leaves the bass dark', () {
      // bin(20 kHz) ≈ 464 → the highest bar 15 (bins 449–511).
      final levels = analyzer.analyze(tone(20000, 1.0, 1024));
      expect(levels.spectrum[15], greaterThan(levels.spectrum[3]));
      expect(levels.spectrum[15], greaterThan(0.0));
      for (var i = 0; i <= 5; i++) {
        expect(levels.spectrum[i], lessThan(levels.spectrum[15] / 4 + 0.01));
      }
    });

    test('mid tone peaks between the low and high cases', () {
      // bin(5 kHz) ≈ 116 → bar 7 (bins 107–128).
      final levels = analyzer.analyze(tone(5000, 1.0, 1024));
      expect(levels.spectrum[7], greaterThan(levels.spectrum[3]));
      expect(levels.spectrum[7], greaterThan(levels.spectrum[14]));
    });
  });
}

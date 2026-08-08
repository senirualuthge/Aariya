import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

/// Directory-level golden comparator configuration — auto-loaded by
/// `flutter test` before any test in this directory runs.
///
/// Golden files are pixel-exact by default. That is correct on macOS, where
/// the reference PNGs are generated (same SDK, same rasterizer ⇒ identical
/// pixels). On Linux CI runners, however, the software rasterizer can round
/// antialiasing a hair differently — the orb paints ~1500 anti-aliased
/// circles, so a handful of edge pixels can legitimately differ with no real
/// regression.
///
/// So on Linux we install a comparator with a SMALL diffPercent tolerance
/// (0.1% of pixels may differ — ~3x the measured rasterizer noise of 0.03%,
/// far too small to mask a genuine visual change). Everywhere else stays
/// strict.
/// `flutter test --update-goldens` bypasses the comparator entirely, so
/// intentional rendering changes still regenerate cleanly.
Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  final GoldenFileComparator base = goldenFileComparator;
  if (Platform.isLinux &&
      !autoUpdateGoldenFiles &&
      base is LocalFileComparator) {
    goldenFileComparator = _TolerantFileComparator(base);
  }
  await testMain();
}

/// Wraps the default [LocalFileComparator] with a pixel-difference tolerance.
///
/// Mirrors the pattern documented in the flutter_test SDK source
/// (`goldens.dart`, `_TolerantGoldenFileComparator`): the comparison passes
/// when the images are identical OR the differing pixel share is within
/// tolerance. Path resolution is delegated to the base comparator so relative
/// golden keys (`goldens/orb_screen_ember.png`) still resolve against the
/// test file's directory.
class _TolerantFileComparator implements GoldenFileComparator {
  _TolerantFileComparator(this._base);

  /// How much the golden image may differ from the test image (0..1).
  /// 0 = identical; 1 = completely different. 0.001 = 0.1% of pixels —
  /// ~3x the 0.03% antialiasing noise measured on a 300×300 orb render.
  static const double _precisionTolerance = 0.001;

  final LocalFileComparator _base;

  @override
  Future<bool> compare(Uint8List imageBytes, Uri golden) async {
    // Resolve the (relative) golden key against the base comparator's basedir
    // — the same directory the test file lives in — then read the PNG bytes.
    final Uri resolved = _base.basedir.resolve(golden.toString());
    final ComparisonResult result = await GoldenFileComparator.compareLists(
      imageBytes,
      await File.fromUri(resolved).readAsBytes(),
    );
    final bool passed =
        result.passed || result.diffPercent <= _precisionTolerance;
    result.dispose();
    return passed;
  }

  @override
  Future<void> update(Uri golden, Uint8List imageBytes) =>
      _base.update(golden, imageBytes);

  @override
  Uri getTestUri(Uri key, int? version) => _base.getTestUri(key, version);
}

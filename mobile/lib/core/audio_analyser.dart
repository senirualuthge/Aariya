import 'dart:async';
import 'dart:math' as math;
import 'package:flutter/foundation.dart';
import 'package:record/record.dart';

/// A single analysed audio frame, mirroring the Web Audio analyser in
/// `aariya-circular-orb.html`:
///
///  * [overall] — smoothed RMS volume (the HTML `volume`), drives orb size,
///    spin speed, glow and particle brightness.
///  * [low] / [mid] / [high] — smoothed average spectral energy in the
///    three bands (0–12%, 12–45%, 45–100% of the spectrum). The HTML uses
///    `mid` for turbulence frequency and `high` for turbulence amplitude.
///  * [spectrum] — a per-bar breakdown (default 16 bars, quadratic-spaced so
///    low frequencies get more bars) for the HUD spectrum analyzer. Empty
///    when a source only provides band levels.
class AudioLevels {
  final double overall;
  final double low;
  final double mid;
  final double high;
  final List<double> spectrum;

  const AudioLevels({
    this.overall = 0,
    this.low = 0,
    this.mid = 0,
    this.high = 0,
    this.spectrum = const [],
  });
}

/// Pure DSP half of the analyser (no plugins) — unit-testable.
///
/// Port of the frontend's `sampleAudio()` + Web Audio `AnalyserNode`:
///  * RMS of the time-domain window → overall volume (`* 2.4`, clamped to 1)
///  * Hann-windowed radix-2 FFT → magnitude spectrum
///  * band averages over the same bin ranges as the HTML
///    (`lowEnd = bins * 0.12`, `midEnd = bins * 0.45`)
///
/// Input samples are expected in [-1, 1].
class PcmAnalyzer {
  /// FFT size in samples. Must be a power of two (default 1024 → 512 bins).
  final int fftSize;

  /// Number of bars in [AudioLevels.spectrum]. Spacing is quadratic (denser
  /// at low frequencies) so the HUD analyzer mirrors the log perception of
  /// pitch, like a real spectrum analyzer.
  final int bars;

  PcmAnalyzer({this.fftSize = 1024, this.bars = 16})
      : assert((fftSize & (fftSize - 1)) == 0, 'fftSize must be a power of two');

  /// Analyzes one window of exactly [fftSize] samples.
  AudioLevels analyze(List<double> samples, {double sensitivity = 1.0}) {
    assert(samples.length == fftSize, 'samples must be exactly fftSize long');

    // ── RMS volume (HTML: rms * sensitivity, then `* 2.4` clamped to 1) ──
    var sumSq = 0.0;
    for (final s in samples) {
      sumSq += s * s;
    }
    final rms = math.sqrt(sumSq / samples.length);
    final volumeTarget = (rms * sensitivity * 2.4).clamp(0.0, 1.0);

    // ── Hann-windowed FFT ────────────────────────────────────────────────
    final re = List<double>.filled(fftSize, 0);
    final im = List<double>.filled(fftSize, 0);
    final n1 = fftSize - 1;
    for (var i = 0; i < fftSize; i++) {
      // Hann window (matches the smooth spectrum of a real analyser).
      final h = 0.5 - 0.5 * math.cos(2 * math.pi * i / n1);
      re[i] = samples[i] * h;
    }
    _fft(re, im);

    final bins = fftSize ~/ 2;
    final lowEnd = (bins * 0.12).floor();
    final midEnd = (bins * 0.45).floor();

    // ── Band energies (HTML: average of band bytes, scaled by sensitivity) ──
    final normalize = 2.0 / fftSize; // peak magnitude of a full-scale tone
    var low = 0.0, mid = 0.0, high = 0.0;
    for (var i = 0; i < lowEnd; i++) {
      low += _magnitude(re[i], im[i]) * normalize;
    }
    for (var i = lowEnd; i < midEnd; i++) {
      mid += _magnitude(re[i], im[i]) * normalize;
    }
    for (var i = midEnd; i < bins; i++) {
      high += _magnitude(re[i], im[i]) * normalize;
    }
    low = (low / lowEnd * sensitivity).clamp(0.0, 1.0);
    mid = (mid / (midEnd - lowEnd) * sensitivity).clamp(0.0, 1.0);
    high = (high / (bins - midEnd) * sensitivity).clamp(0.0, 1.0);

    // ── Spectrum bars (quadratic bin spacing, DC bin skipped) ────────────
    final spectrum = List<double>.filled(bars, 0);
    if (bars > 1 && bins > 1) {
      // boundary(bars) == bins - 1, so the final bar stops exactly at the
      // last real bin (no double-counting of the mirrored FFT region).
      double boundary(int i) =>
          1 + (bins - 2) * (i * i) / (bars * bars);
      var start = 1;
      for (var bar = 0; bar < bars; bar++) {
        final end = boundary(bar + 1).floor();
        final count = end - start;
        if (count > 0) {
          var acc = 0.0;
          for (var i = start; i < end; i++) {
            acc += _magnitude(re[i], im[i]) * normalize;
          }
          spectrum[bar] = (acc / count * sensitivity).clamp(0.0, 1.0);
        }
        start = end;
      }
    }

    return AudioLevels(
      overall: volumeTarget,
      low: low,
      mid: mid,
      high: high,
      spectrum: spectrum,
    );
  }

  static double _magnitude(double re, double im) =>
      math.sqrt(re * re + im * im);

  /// Iterative in-place radix-2 FFT. [re]/[im] length must be a power of two.
  static void _fft(List<double> re, List<double> im) {
    final n = re.length;

    // Bit-reversal permutation.
    var j = 0;
    for (var i = 1; i < n; i++) {
      var bit = n >> 1;
      while (j & bit != 0) {
        j ^= bit;
        bit >>= 1;
      }
      j ^= bit;
      if (i < j) {
        var t = re[i];
        re[i] = re[j];
        re[j] = t;
        t = im[i];
        im[i] = im[j];
        im[j] = t;
      }
    }

    // Butterfly stages.
    for (var len = 2; len <= n; len <<= 1) {
      final ang = -2 * math.pi / len;
      final wRe = math.cos(ang);
      final wIm = math.sin(ang);
      final half = len ~/ 2;
      for (var i = 0; i < n; i += len) {
        var curRe = 1.0, curIm = 0.0;
        for (var k = 0; k < half; k++) {
          final uRe = re[i + k];
          final uIm = im[i + k];
          final o = i + k + half;
          final vRe = re[o] * curRe - im[o] * curIm;
          final vIm = re[o] * curIm + im[o] * curRe;
          re[i + k] = uRe + vRe;
          im[i + k] = uIm + vIm;
          re[o] = uRe - vRe;
          im[o] = uIm - vIm;
          final nRe = curRe * wRe - curIm * wIm;
          curIm = curRe * wIm + curIm * wRe;
          curRe = nRe;
        }
      }
    }
  }
}

/// Mic-powered analyser: streams raw PCM16 via the `record` package, decodes
/// it into float samples and emits smoothed [AudioLevels] frames.
///
/// The smoothing constants are a direct port of the HTML's `sampleAudio()`:
/// volume attack 0.35, band attack/decay 0.3 — so the orb never jitters with
/// raw mic energy.
class AudioAnalyser {
  /// Shared, app-wide analyser. The mic is a single hardware resource and
  /// both the home orb and the voice overlay must read the same stream — two
  /// live recorders would fight over the input device. Only one consumer may
  /// run it at a time (the overlay runs it while the AI speaks; the home orb
  /// runs it for ambient visualization).
  static final AudioAnalyser instance = AudioAnalyser._();

  AudioAnalyser._();

  final AudioRecorder _recorder = AudioRecorder();
  final PcmAnalyzer _analyzer = PcmAnalyzer();

  final StreamController<AudioLevels> _levelsController =
      StreamController<AudioLevels>.broadcast();

  /// Live stream of smoothed audio levels. Emits ~20–40 Hz while recording.
  Stream<AudioLevels> get levels => _levelsController.stream;

  /// Number of bars in each frame's [AudioLevels.spectrum] (HUD analyzer).
  int get bars => _analyzer.bars;

  /// Sensitivity multiplier (HUD slider, 0.5–3, default 1.4). Applied live.
  double sensitivity = 1.4;

  final List<double> _buffer = [];
  double _volume = 0, _low = 0, _mid = 0, _high = 0;
  late List<double> _spectrum = List.filled(_analyzer.bars, 0);
  StreamSubscription<Uint8List>? _sub;
  bool _running = false;

  bool get isRunning => _running;

  /// Requests mic access and starts the raw PCM stream. Returns false (and
  /// never throws) when the mic is unavailable or permission is denied.
  Future<bool> start() async {
    if (_running) return true;
    try {
      final granted = await _recorder.hasPermission();
      if (!granted) return false;

      final stream = await _recorder.startStream(const RecordConfig(
        encoder: AudioEncoder.pcm16bits,
        sampleRate: 44100,
        numChannels: 1,
      ));
      _running = true;
      _sub = stream.listen(
        _onPcm,
        onError: (Object e) => debugPrint('[Analyser] stream error: $e'),
      );
      return true;
    } catch (e) {
      debugPrint('[Analyser] start failed: $e');
      return false;
    }
  }

  /// Stops the stream, resets state and emits a zero frame so the orb
  /// returns to its idle breathing animation.
  Future<void> stop() async {
    await _sub?.cancel();
    _sub = null;
    _running = false;
    try {
      await _recorder.stop();
    } catch (_) {}
    _buffer.clear();
    _volume = _low = _mid = _high = 0;
    final zeroSpectrum = List.filled(_spectrum.length, 0.0);
    _spectrum = zeroSpectrum;
    if (!_levelsController.isClosed) {
      // Defensive copy — never hand out the internal state list.
      _levelsController.add(AudioLevels(spectrum: List.of(zeroSpectrum)));
    }
  }

  Future<void> dispose() async {
    try {
      await stop();
    } catch (_) {}
    try {
      await _recorder.dispose();
    } catch (_) {}
    await _levelsController.close();
  }

  void _onPcm(Uint8List bytes) {
    final view = ByteData.sublistView(bytes);
    final count = bytes.length ~/ 2;
    for (var i = 0; i < count; i++) {
      _buffer.add(view.getInt16(i * 2, Endian.little) / 32768.0);
    }

    // Analyze the most recent full window, keep the remainder for overlap.
    while (_buffer.length >= _analyzer.fftSize) {
      final window = _buffer.sublist(_buffer.length - _analyzer.fftSize);
      _buffer.clear();
      final target = _analyzer.analyze(window, sensitivity: sensitivity);

      // HTML attack/decay smoothing (lerp with fixed factors).
      _volume += (target.overall - _volume) * 0.35;
      _low += (target.low - _low) * 0.3;
      _mid += (target.mid - _mid) * 0.3;
      _high += (target.high - _high) * 0.3;
      for (var i = 0; i < _spectrum.length; i++) {
        _spectrum[i] += (target.spectrum[i] - _spectrum[i]) * 0.3;
      }

      if (_levelsController.hasListener) {
        _levelsController.add(
          AudioLevels(
            overall: _volume,
            low: _low,
            mid: _mid,
            high: _high,
            spectrum: List.of(_spectrum),
          ),
        );
      }
    }
  }
}

import 'dart:math' as math;
import 'dart:typed_data';
import 'package:flutter/material.dart';

/// Flutter port of the frontend `OrbAvatar.jsx` — a voice-reactive particle
/// orb. A shell of particles on a fibonacci sphere is perturbed by a cheap
/// analytic noise field whose amplitude, frequency and spin all scale with the
/// incoming [level] (live mic / audio energy, 0..1). Idle = gentle breathing.
///
/// Rendering is a plain [CustomPainter] (no three.js), tuned to stay smooth on
/// a phone: ~1500 particles, one `Paint` reused, additive glow via a radial
/// gradient core.
class VoiceReactiveOrb extends StatefulWidget {
  /// Live voice/audio energy in 0..1. 0 = idle breathing animation.
  final double level;

  /// Smoothed spectral band energies (0..1) from the audio analyser.
  /// Mirrors the HTML: [bandMid] drives the noise-field frequency, [bandHigh]
  /// adds turbulence amplitude on top of [level]. Defaults to 0 → the
  /// classic level-only behavior. (The low band is computed by the analyser
  /// but — like the HTML — never affects the particle rendering.)
  final double bandMid;
  final double bandHigh;

  /// Pixel diameter of the orb widget.
  final double size;

  /// Color stops for the hue ramp (cosmic theme by default).
  final List<Color> theme;

  /// Extra Y-axis rotation (radians) applied on top of the auto-spin.
  /// Ported from the HTML orb's "drag to rotate" — parent accumulates drag
  /// deltas into these offsets.
  final double extraRotY;

  /// Extra X-axis rotation (radians) applied on top of the idle tilt.
  /// Clamp to roughly ±0.9 (as the frontend does) before passing in.
  final double extraRotX;

  const VoiceReactiveOrb({
    super.key,
    this.level = 0,
    this.bandMid = 0,
    this.bandHigh = 0,
    this.size = 220,
    this.theme = _cosmicStops,
    this.extraRotY = 0,
    this.extraRotX = 0,
  });

  static const List<Color> _cosmicStops = [
    Color(0xFF33E6FF),
    Color(0xFF5B6BFF),
    Color(0xFF9B3FFF),
    Color(0xFFFF2F8F),
    Color(0xFFFF3B3B),
    Color(0xFFFF8A2E),
    Color(0xFF33E6FF),
  ];

  static const List<Color> _emberStops = [
    Color(0xFFFFE08A),
    Color(0xFFFFB23C),
    Color(0xFFFF7A3C),
    Color(0xFFFF3C5C),
    Color(0xFFC23CFF),
    Color(0xFFFFB23C),
    Color(0xFFFFE08A),
  ];

  static const List<Color> _monoStops = [
    Color(0xFFFFFFFF),
    Color(0xFFB9BDE0),
    Color(0xFF7A7FB0),
    Color(0xFFB9BDE0),
    Color(0xFFFFFFFF),
    Color(0xFFDFE1FF),
    Color(0xFFFFFFFF),
  ];

  /// Named themes mirroring the frontend.
  static List<Color> themeNamed(String name) {
    switch (name) {
      case 'ember':
        return _emberStops;
      case 'mono':
        return _monoStops;
      default:
        return _cosmicStops;
    }
  }

  @override
  State<VoiceReactiveOrb> createState() => _VoiceReactiveOrbState();
}

class _VoiceReactiveOrbState extends State<VoiceReactiveOrb>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  double _smoothLevel = 0;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 60),
    )..repeat();
    _controller.addListener(_smooth);
  }

  void _smooth() {
    // Slow attack / decay so the orb doesn't jitter with raw mic levels.
    final target = widget.level;
    final prev = _smoothLevel;
    final step = target > prev ? 0.25 : 0.12;
    _smoothLevel = prev + (target - prev) * step;
    if (_smoothLevel < 0.001 && target == 0) _smoothLevel = 0;
  }

  @override
  void dispose() {
    _controller.removeListener(_smooth);
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return CustomPaint(
      size: Size.square(widget.size),
      painter: _OrbPainter(
        t: _controller.value * 60.0,
        level: _smoothLevel,
        bandMid: widget.bandMid,
        bandHigh: widget.bandHigh,
        theme: widget.theme,
        extraRotY: widget.extraRotY,
        extraRotX: widget.extraRotX,
        repaint: _controller,
      ),
    );
  }
}

// ────────────────────────────────────────────────────────────────────────────
// Painter
// ────────────────────────────────────────────────────────────────────────────

/// Precomputed fibonacci-sphere base directions (unit vectors) + seeds,
/// shared across all instances so a rebuild never recomputes them.
final List<double> _baseDirs = _buildBase();
final List<double> _seeds = _buildSeeds();
final Uint8List _sparkle = _buildSparkle();

const int _particleCount = 1500;

List<double> _buildBase() {
  final out = List<double>.filled(_particleCount * 3, 0);
  final golden = math.pi * (3 - math.sqrt(5));
  for (var i = 0; i < _particleCount; i++) {
    final y = 1 - (i / (_particleCount - 1)) * 2;
    final rad = math.sqrt(math.max(0, 1 - y * y));
    final th = golden * i;
    out[i * 3] = math.cos(th) * rad;
    out[i * 3 + 1] = y;
    out[i * 3 + 2] = math.sin(th) * rad;
  }
  return out;
}

List<double> _buildSeeds() {
  final rng = math.Random(42);
  return List<double>.generate(
    _particleCount,
    (_) => rng.nextDouble() * 1000,
  );
}

Uint8List _buildSparkle() {
  final rng = math.Random(7);
  final out = Uint8List(_particleCount);
  for (var i = 0; i < _particleCount; i++) {
    out[i] = rng.nextDouble() < 0.02 ? 1 : 0;
  }
  return out;
}

/// The frontend's analytic noise (direct port of `OrbAvatar.jsx`).
double _noise3(double x, double y, double z) {
  return (math.sin(x * 1.0 + z * 0.7) * math.cos(y * 1.3 - z * 0.4) +
          math.sin(x * 2.1 - y * 1.7 + z * 1.1) * 0.5 +
          math.sin(x * 4.3 + y * 3.9 - z * 2.2) * 0.25) /
      1.75;
}

/// Color ramp over the theme stops, t in 0..1 (port of the JS `ramp`).
Color _ramp(double t, List<Color> stops) {
  final segs = stops.length - 1;
  final scaled = math.min(0.999999, math.max(0.0, t)) * segs;
  final i = scaled.floor();
  final localT = scaled - i;
  final c0 = stops[i];
  final c1 = stops[i + 1];
  return Color.fromARGB(
    255,
    ((c0.r + (c1.r - c0.r) * localT) * 255).round(),
    ((c0.g + (c1.g - c0.g) * localT) * 255).round(),
    ((c0.b + (c1.b - c0.b) * localT) * 255).round(),
  );
}

class _OrbPainter extends CustomPainter {
  final double t;
  final double level;
  final double bandMid;
  final double bandHigh;
  final List<Color> theme;
  final double extraRotY;
  final double extraRotX;

  _OrbPainter({
    required this.t,
    required this.level,
    this.bandMid = 0,
    this.bandHigh = 0,
    required this.theme,
    this.extraRotY = 0,
    this.extraRotX = 0,
    super.repaint,
  });

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    final cy = size.height / 2;
    final baseRadius = size.shortestSide * 0.36;

    // Auto-rotation: idle spin + speed-up with voice level.
    // `extraRotY/extraRotX` are the drag offsets accumulated by the parent
    // (port of the HTML orb's "drag to rotate"). extraRotY is modded by 2π
    // so long drag sessions never degrade sin/cos precision.
    final autoSpeed = 0.05 + level * 0.15;
    final rotY = 0.2 + t * autoSpeed + extraRotY % (2 * math.pi);
    final rotX = (0.08 + extraRotX).clamp(-0.9, 0.9);

    // Port of the HTML `updateParticles`: bandHigh feeds turbulence
    // amplitude, bandMid feeds turbulence frequency, level drives spin/size.
    final turbAmp = 0.10 + level * 0.45 + bandHigh * 0.28;
    final turbFreq = 1.4 + bandMid;
    final timeScale = t * 0.14 + level * 0.35;
    const persp = 2.5;

    final paint = Paint();
    for (var i = 0; i < _particleCount; i++) {
      final ix = i * 3;
      final dx = _baseDirs[ix];
      final dy = _baseDirs[ix + 1];
      final dz = _baseDirs[ix + 2];

      final n = _noise3(
        dx * turbFreq + timeScale,
        dy * turbFreq - timeScale * 0.7,
        dz * turbFreq + _seeds[i] * 0.001,
      );
      final outward = 1 + n * turbAmp;

      // Rotate (Y then X) the unit direction.
      final cy0 = math.cos(rotY), sy0 = math.sin(rotY);
      final cx0 = math.cos(rotX), sx0 = math.sin(rotX);
      final rx = dx * cy0 + dz * sy0;
      final rz = -dx * sy0 + dz * cy0;
      final ry = dy * cx0 - rz * sx0;
      final rz2 = dy * sx0 + rz * cx0;

      final depth = persp / (persp + rz2 * outward);
      final px = cx + rx * outward * depth * baseRadius;
      final py = cy + ry * outward * depth * baseRadius;

      // Hue ramp from direction, nudged by noise.
      var tt = (math.atan2(rx, ry) / (math.pi * 2) + 1) % 1;
      tt = (tt + n * 0.05 + 1) % 1;
      var col = _ramp(tt, theme);

      var bright = 0.42 + math.max(0, n) * 0.9 + level * 0.42;
      if (_sparkle[i] == 1) {
        bright += 0.4 + 0.4 * math.sin(t * 3 + _seeds[i]);
      }
      final mix = (bright - 0.5).clamp(0.0, 1.0) * 0.62;

      final cr = col.r + (1 - col.r) * mix;
      final cg = col.g + (1 - col.g) * mix;
      final cb = col.b + (1 - col.b) * mix;

      final alpha = (0.55 + bright * 0.35).clamp(0.0, 0.9);
      paint.color = Color.fromARGB(
        (alpha * 255).round(),
        (cr * 255).round(),
        (cg * 255).round(),
        (cb * 255).round(),
      );

      final radius = (0.8 + level * 0.8 * bright).clamp(0.5, 2.6) * depth;
      canvas.drawCircle(Offset(px, py), radius, paint);
    }

    // Core glow sphere (radial gradient), pulsing with level.
    final glow = Paint()
      ..shader = RadialGradient(
        colors: [
          const Color(0xFFFFFFFF).withValues(alpha: 0.55),
          _ramp((t * 0.03) % 1, theme).withValues(alpha: 0.35),
          Colors.transparent,
        ],
        stops: const [0.0, 0.55, 1.0],
      ).createShader(Rect.fromCircle(
        center: Offset(cx, cy),
        radius: baseRadius,
      ));
    final pulse = baseRadius * (1 + level * 0.35);
    canvas.drawCircle(Offset(cx, cy), pulse, glow);
  }

  @override
  bool shouldRepaint(covariant _OrbPainter oldDelegate) =>
      oldDelegate.t != t ||
      oldDelegate.level != level ||
      oldDelegate.bandMid != bandMid ||
      oldDelegate.bandHigh != bandHigh ||
      oldDelegate.extraRotY != extraRotY ||
      oldDelegate.extraRotX != extraRotX;
}

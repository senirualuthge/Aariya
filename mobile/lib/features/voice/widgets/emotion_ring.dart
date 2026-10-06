import 'package:flutter/material.dart';
import '../../../core/state/brain_state_controller.dart';

/// Rotating ring around the Avatar Orb.
/// Arousal → speed + thickness + opacity. Calm = slow thin ring. Excited = fast thick vivid ring.
class EmotionRing extends StatefulWidget {
  final BrainStateController brain;
  final double orbSize;

  const EmotionRing({
    super.key,
    required this.brain,
    this.orbSize = 160,
  });

  @override
  State<EmotionRing> createState() => _EmotionRingState();
}

class _EmotionRingState extends State<EmotionRing>
    with SingleTickerProviderStateMixin {
  late final AnimationController _rotateController;

  @override
  void initState() {
    super.initState();
    _rotateController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 6),
    )..repeat();

    // Speed reacts to arousal — we update duration dynamically
    widget.brain.addListener(_updateSpeed);
  }

  void _updateSpeed() {
    if (!mounted) return;
    final arousal = widget.brain.emotionArousal;
    // arousal 0.0 → 6s per revolution, 1.0 → 1.5s per revolution
    final seconds = (6.0 - arousal * 4.5).clamp(1.5, 6.0);
    _rotateController.duration = Duration(
      milliseconds: (seconds * 1000).toInt(),
    );
    if (!_rotateController.isAnimating) _rotateController.repeat();
  }

  @override
  void dispose() {
    widget.brain.removeListener(_updateSpeed);
    _rotateController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: Listenable.merge([widget.brain, _rotateController]),
      builder: (context, _) {
        final arousal = widget.brain.emotionArousal;
        final ringOpacity = (0.2 + arousal * 0.65).clamp(0.0, 1.0);
        final ringWidth = (1.5 + arousal * 5).clamp(1.5, 6.5);
        final size = widget.orbSize + 28.0 + arousal * 16;

        // Color matches the orb valence
        final valence = widget.brain.emotionValence;
        final Color ringColor;
        if (valence > 0.4) {
          ringColor = const Color(0xFF3BAFDA);
        } else if (valence < -0.4) {
          ringColor = const Color(0xFFE74C5E);
        } else {
          ringColor = const Color(0xFF8888EE);
        }

        return RotationTransition(
          turns: _rotateController,
          child: Container(
            width: size,
            height: size,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              border: Border.all(
                color: ringColor.withValues(alpha: ringOpacity),
                width: ringWidth,
              ),
            ),
          ),
        );
      },
    );
  }
}

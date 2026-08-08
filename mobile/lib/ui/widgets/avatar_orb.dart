import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../../brain/client_brain.dart';

/// The AI's emotional "face."
/// Size, color, and glow are all driven live by [BrainStateController].
///
/// Emotion mapping:
///   valence > 0.4  → warm blue (positive / happy)
///   valence < -0.4 → rose red  (negative / distressed)
///   neutral        → deep blue (Purple Ban adhered to)
class AvatarOrb extends StatefulWidget {
  final ClientBrain brain;
  /// Optional forced offset for attention-shift animations from parent.
  final Offset attentionOffset;

  const AvatarOrb({
    super.key,
    required this.brain,
    this.attentionOffset = Offset.zero,
  });

  @override
  State<AvatarOrb> createState() => _AvatarOrbState();
}

class _AvatarOrbState extends State<AvatarOrb>
    with SingleTickerProviderStateMixin {
  late final AnimationController _breathController;
  late final Animation<double> _breathAnim;

  @override
  void initState() {
    super.initState();
    _breathController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 4),
    )..repeat(reverse: true);

    _breathAnim = Tween<double>(begin: 0.0, end: 1.0).animate(
      CurvedAnimation(parent: _breathController, curve: Curves.easeInOut),
    );
  }

  @override
  void dispose() {
    _breathController.dispose();
    super.dispose();
  }

  Color _valenceToColor(double valence) {
    if (valence > 0.4) {
      // Positive — luminous cyan-blue
      return const Color(0xFF3BAFDA);
    } else if (valence < -0.4) {
      // Negative — warm rose
      return const Color(0xFFE74C5E);
    } else {
      // Neutral — deep dark blue (strict "no-purple" rule adhered to)
      return const Color(0xFF1E3A8A);
    }
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: Listenable.merge([widget.brain, _breathAnim]),
      builder: (context, _) {
        final brain = widget.brain;
        final breath = _breathAnim.value;
        final arousal = brain.emotionArousal;
        final energy = brain.energy;
        final isSpeaking = brain.state == ConversationState.speaking || brain.state == ConversationState.streaming;

        // Base size grows with energy; breath adds subtle ±10 px idle movement
        final breathPulse = isSpeaking ? 0.0 : breath * 10;
        final speakPulse = isSpeaking
            ? math.sin(DateTime.now().millisecondsSinceEpoch / 150) * arousal * 14
            : 0.0;
        final size = (120.0 + energy * 50 + breathPulse + speakPulse)
            .clamp(110.0, 210.0);

        final color = _valenceToColor(brain.emotionValence);
        final glowIntensity = 0.3 + arousal * 0.55;

        return AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          curve: Curves.easeOut,
          width: size,
          height: size,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            gradient: RadialGradient(
              colors: [
                color.withValues(alpha: 0.9),
                color.withValues(alpha: 0.35),
                Colors.black.withValues(alpha: 0.0),
              ],
              stops: const [0.0, 0.55, 1.0],
            ),
            boxShadow: [
              BoxShadow(
                color: color.withValues(alpha: glowIntensity),
                blurRadius: 40 + arousal * 30,
                spreadRadius: 6 + arousal * 12,
              ),
              BoxShadow(
                color: color.withValues(alpha: 0.15),
                blurRadius: 80,
                spreadRadius: 20,
              ),
            ],
          ),
          child: (brain.state == ConversationState.processing)
              ? Center(
                  child: SizedBox(
                    width: size * 0.3,
                    height: size * 0.3,
                    child: CircularProgressIndicator(
                      strokeWidth: 2,
                      color: Colors.white.withValues(alpha: 0.7),
                    ),
                  ),
                )
              : null,
        );
      },
    );
  }
}

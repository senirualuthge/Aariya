part of 'voice_conversation_overlay.dart';

// ── Helpers ────────────────────────────────────────────────────────────────────

/// Status-pill tint — mirrors the presence chip's mode color so the pill and
/// chip stay in sync during a call. Falls back to state-accent colors only
/// before the first synoptic (mode) arrives, so a no-data call is never
/// miscolored as CALM.
@visibleForTesting
Color statusPillColor(VoiceState state, String mode) {
  if (mode.isNotEmpty) return modeColor(mode);
  return switch (state) {
    VoiceState.listening  => Colors.greenAccent,
    VoiceState.processing => Colors.orangeAccent,
    VoiceState.speaking   => const Color(0xFF3BAFDA),
  };
}

class _StatusPill extends StatelessWidget {
  final String label;
  final Color color;

  const _StatusPill({super.key, required this.label, required this.color});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        border: Border.all(color: color.withValues(alpha: 0.5), width: 1),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 11,
          fontWeight: FontWeight.bold,
          letterSpacing: 2.0,
        ),
      ),
    );
  }
}

class _CircleButton extends StatelessWidget {
  final IconData icon;
  final Color color;
  final VoidCallback onTap;

  const _CircleButton({
    required this.icon,
    required this.color,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 56,
        height: 56,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: Colors.white.withValues(alpha: 0.06),
          border: Border.all(color: color.withValues(alpha: 0.45), width: 1.5),
        ),
        child: Icon(icon, color: color, size: 26),
      ),
    );
  }
}

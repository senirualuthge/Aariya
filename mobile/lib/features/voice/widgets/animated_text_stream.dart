import 'package:flutter/material.dart';

/// Displays text as it streams in token by token.
/// Shows a blinking cursor while streaming, fades the cursor out on completion.
class AnimatedTextStream extends StatefulWidget {
  final String text;
  final bool isStreaming;
  final TextStyle? style;
  final TextAlign textAlign;

  const AnimatedTextStream({
    super.key,
    required this.text,
    this.isStreaming = false,
    this.style,
    this.textAlign = TextAlign.center,
  });

  @override
  State<AnimatedTextStream> createState() => _AnimatedTextStreamState();
}

class _AnimatedTextStreamState extends State<AnimatedTextStream>
    with SingleTickerProviderStateMixin {
  late final AnimationController _cursorController;
  late final Animation<double> _cursorAnim;

  @override
  void initState() {
    super.initState();
    _cursorController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 530),
    )..repeat(reverse: true);

    _cursorAnim = CurvedAnimation(
      parent: _cursorController,
      curve: Curves.easeInOut,
    );
  }

  @override
  void dispose() {
    _cursorController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    const defaultStyle = TextStyle(
      color: Colors.white,
      fontSize: 17,
      fontWeight: FontWeight.w400,
      height: 1.5,
    );
    final effectiveStyle = widget.style ?? defaultStyle;

    return AnimatedBuilder(
      animation: _cursorAnim,
      builder: (context, _) {
        // Build cursor character with blinking opacity
        final cursor = widget.isStreaming
            ? TextSpan(
                text: '▎',
                style: effectiveStyle.copyWith(
                  color: Colors.white.withValues(alpha: _cursorAnim.value),
                ),
              )
            : null;

        return RichText(
          textAlign: widget.textAlign,
          text: TextSpan(
            children: [
              TextSpan(text: widget.text, style: effectiveStyle),
              ?cursor,
            ],
          ),
        );
      },
    );
  }
}

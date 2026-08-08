import 'package:aariya_mobile/services/websocket_service.dart';
import 'package:aariya_mobile/state/chat_controller.dart';
import 'package:aariya_mobile/ui/screens/chat_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Minimal harness that reproduces ChatScreen's `command_denied` listener
/// wiring and shows the snackbar through the SAME production static the real
/// screen uses (ChatScreen.showCommandDenied) — so the test asserts the exact
/// UI text/behavior, not a re-implementation of it.
class _CommandDeniedHarness extends StatefulWidget {
  const _CommandDeniedHarness({required this.controller});

  final ChatController controller;

  @override
  State<_CommandDeniedHarness> createState() => _CommandDeniedHarnessState();
}

class _CommandDeniedHarnessState extends State<_CommandDeniedHarness> {
  @override
  void initState() {
    super.initState();
    widget.controller.commandDenied.addListener(_onDenied);
  }

  @override
  void dispose() {
    widget.controller.commandDenied.removeListener(_onDenied);
    super.dispose();
  }

  void _onDenied() {
    final denied = widget.controller.commandDenied.value;
    if (denied == null || !mounted) return;
    ChatScreen.showCommandDenied(context, denied);
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(body: SizedBox.shrink());
  }
}

void main() {
  testWidgets('command_denied frame surfaces the snackbar', (tester) async {
    // A fresh, isolated controller. It subscribes to the real
    // WebSocketService stream — the same one the app uses — so emitting a
    // test frame exercises the genuine frame-handling path.
    // NOTE: controller.dispose() is intentionally NOT called here — it invokes
    // FlutterTts.stop() over a platform channel, which throws
    // MissingPluginException under flutter test. The fresh-instance-per-test
    // pattern plus the harness State.dispose() (which removes the notifier
    // listener) keeps teardown clean without touching the TTS channel.
    final controller = ChatController();

    await tester.pumpWidget(MaterialApp(
      home: _CommandDeniedHarness(controller: controller),
    ));

    // Simulate the server refusing an authority-only command on the shared
    // mobile channel (see server/systems/security/mobile_authority.py).
    WebSocketService.instance.emitTestFrame({
      'type': 'command_denied',
      'action': 'wipe_memory',
      'reason': 'authority_required',
    });

    // Let the stream microtask deliver the frame, the ValueNotifier fire,
    // and the snackbar entrance animation run.
    await tester.pumpAndSettle();

    // The prettified action name (underscores → spaces) must appear in the
    // exact production snackbar message.
    expect(
      find.text('"wipe memory" is laptop-dashboard only — denied by Aariya'),
      findsOneWidget,
    );
  });

  testWidgets('multiple denials update the snackbar message', (tester) async {
    // NOTE: controller.dispose() is intentionally NOT called here — it invokes
    // FlutterTts.stop() over a platform channel, which throws
    // MissingPluginException under flutter test. The fresh-instance-per-test
    // pattern plus the harness State.dispose() (which removes the notifier
    // listener) keeps teardown clean without touching the TTS channel.
    final controller = ChatController();

    await tester.pumpWidget(MaterialApp(
      home: _CommandDeniedHarness(controller: controller),
    ));

    WebSocketService.instance.emitTestFrame({
      'type': 'command_denied',
      'action': 'set_personality',
    });
    await tester.pumpAndSettle();
    expect(
      find.text('"set personality" is laptop-dashboard only — denied by Aariya'),
      findsOneWidget,
    );

    // A second, different refusal replaces the previous snackbar's message.
    WebSocketService.instance.emitTestFrame({
      'type': 'command_denied',
      'action': 'force_mode',
    });
    await tester.pumpAndSettle();
    expect(
      find.text('"force mode" is laptop-dashboard only — denied by Aariya'),
      findsOneWidget,
    );
  });

  testWidgets('non-denied frames never trigger the snackbar', (tester) async {
    // NOTE: controller.dispose() is intentionally NOT called here — it invokes
    // FlutterTts.stop() over a platform channel, which throws
    // MissingPluginException under flutter test. The fresh-instance-per-test
    // pattern plus the harness State.dispose() (which removes the notifier
    // listener) keeps teardown clean without touching the TTS channel.
    final controller = ChatController();

    await tester.pumpWidget(MaterialApp(
      home: _CommandDeniedHarness(controller: controller),
    ));

    // Ordinary chat traffic must not surface a denial.
    WebSocketService.instance.emitTestFrame({
      'type': 'text.stream',
      'chunk': 'hello',
    });
    WebSocketService.instance.emitTestFrame({
      'type': 'state.update',
      'state': {'emotion': 'calm'},
    });
    await tester.pumpAndSettle();

    expect(find.byType(SnackBar), findsNothing);
  });
}

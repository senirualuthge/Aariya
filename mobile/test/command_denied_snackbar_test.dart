import 'dart:convert';

import 'package:aariya_mobile/services/websocket_service.dart';
import 'package:aariya_mobile/state/chat_controller.dart';
import 'package:aariya_mobile/ui/screens/chat_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:stream_channel/stream_channel.dart';

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

  testWidgets('server command_denied payload (reason + detail) over a fake socket',
      (tester) async {
    // NOTE: controller.dispose() skipped — FlutterTts.stop() hits a platform
    // channel under flutter test (see earlier tests).
    final controller = ChatController();

    // A real StreamChannelController pair: `local` is the fake SERVER side,
    // `foreign` is what we hand the WebSocketService as its control channel.
    final socket = StreamChannelController<dynamic>();
    WebSocketService.instance.attachControlChannel(socket.foreign);
    addTearDown(() => socket.local.sink.close());

    // Capture the decoded frame as ChatController sees it, so we can assert
    // the FULL server payload shape (reason + detail) survived the socket →
    // _decodeFrame → messagesStream path — not just the action-derived state.
    Map<String, dynamic>? decodedFrame;
    final sub = WebSocketService.instance.messagesStream.listen((frame) {
      if (frame['type'] == 'command_denied') decodedFrame = frame;
    });
    addTearDown(sub.cancel);

    await tester.pumpWidget(MaterialApp(
      home: _CommandDeniedHarness(controller: controller),
    ));

    // Exactly what server/systems/security/mobile_authority.py's
    // denied_frame() sends for a refused wipe_memory — raw JSON over the
    // socket, the same bytes a live /ws/mobile/control connection carries.
    socket.local.sink.add(jsonEncode({
      'type': 'command_denied',
      'action': 'wipe_memory',
      'reason': 'authority_required',
      'detail': 'This command requires the laptop dashboard (authority layer).',
    }));

    await tester.pumpAndSettle();

    // The full server payload survives the socket → decode → ChatController
    // path: every field of denied_frame() arrives intact...
    expect(decodedFrame, isNotNull);
    final frame = decodedFrame!;
    expect(frame['type'], 'command_denied');
    expect(frame['action'], 'wipe_memory');
    expect(frame['reason'], 'authority_required');
    expect(
      frame['detail'],
      'This command requires the laptop dashboard (authority layer).',
    );
    // ...and the prettified action surfaces in the snackbar.
    expect(controller.commandDenied.value, 'wipe memory');
    expect(
      find.text('"wipe memory" is laptop-dashboard only — denied by Aariya'),
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

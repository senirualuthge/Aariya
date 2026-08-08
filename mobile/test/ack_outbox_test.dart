import 'package:aariya_mobile/services/ack_outbox.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('AckOutbox — enqueue', () {
    test('stamps id + requires_ack and sends immediately', () {
      final outbox = AckOutbox();
      final sent = <Map<String, dynamic>>[];

      final id = outbox.enqueue(
        {'type': 'input.multimodal', 'content': 'hi'},
        (envelope) => sent.add(envelope),
      );

      expect(id, isNotEmpty);
      expect(outbox.pendingCount, 1);
      expect(sent, hasLength(1));
      expect(sent.single['id'], id);
      expect(sent.single['requires_ack'], isTrue);
      expect(sent.single['type'], 'input.multimodal');
      outbox.dispose();
    });
  });

  group('AckOutbox — ack', () {
    test('removes the pending message and lifts degraded', () {
      final outbox = AckOutbox();
      final id = outbox.enqueue({'type': 'command', 'action': 'ping'}, (_) {});

      // Force degraded, then prove a fresh ack clears it.
      outbox.isDegraded.value = true;
      outbox.ack(id);

      expect(outbox.pendingCount, 0);
      expect(outbox.isDegraded.value, isFalse);
      outbox.dispose();
    });

    test('ignores acks for unknown ids', () {
      final outbox = AckOutbox();
      outbox.enqueue({'type': 'command'}, (_) {});
      outbox.ack('nope');
      expect(outbox.pendingCount, 1);
      outbox.dispose();
    });
  });

  group('AckOutbox — retry + degrade', () {
    test('re-sends with exponential backoff until acked', () {
      fakeAsync((async) {
        final outbox = AckOutbox(
          retryBase: const Duration(milliseconds: 500),
          maxRetries: 3,
        );
        final sends = <String>[];
        final id =
            outbox.enqueue({'type': 'command'}, (e) => sends.add(e['id'] as String));

        // No ACK arrives — the message should be re-sent on a backoff ladder.
        async.elapse(const Duration(milliseconds: 500)); // attempt 1
        expect(sends, hasLength(2));
        async.elapse(const Duration(milliseconds: 1000)); // attempt 2
        expect(sends, hasLength(3));

        // ACK arrives before the 3rd retry — no further sends.
        outbox.ack(id);
        async.elapse(const Duration(seconds: 10));
        expect(sends, hasLength(3));
        expect(outbox.pendingCount, 0);
        expect(outbox.isDegraded.value, isFalse);
      });
    });

    test('drops after maxRetries and enters degraded state', () {
      fakeAsync((async) {
        final outbox = AckOutbox(
          retryBase: const Duration(milliseconds: 500),
          maxRetries: 3,
        );
        final sends = <String>[];
        outbox.enqueue({'type': 'command'}, (e) => sends.add(e['id'] as String));
        expect(outbox.isDegraded.value, isFalse);

        // initial + 3 retries = 4 sends, then it is dropped and degraded.
        async.elapse(const Duration(seconds: 30));
        expect(sends, hasLength(4));
        expect(outbox.pendingCount, 0);
        expect(outbox.isDegraded.value, isTrue);
      });
    });

    test('multiple messages retry independently', () {
      fakeAsync((async) {
        final outbox = AckOutbox(maxRetries: 2);
        final ids = <String>[];
        outbox.enqueue({'type': 'a'}, (e) => ids.add(e['id'] as String));
        final second = outbox.enqueue({'type': 'b'}, (e) => ids.add(e['id'] as String));

        async.elapse(const Duration(milliseconds: 500)); // both attempt 1
        outbox.ack(second); // 'b' acked, 'a' keeps retrying
        async.elapse(const Duration(seconds: 5));

        expect(outbox.pendingCount, 0);
        expect(outbox.isDegraded.value, isTrue);
      });
    });
  });

  group('AckOutbox — flush', () {
    test('re-sends all pending immediately and resets retry budget', () {
      fakeAsync((async) {
        final outbox = AckOutbox(maxRetries: 2);
        final sends = <Map<String, dynamic>>[];
        outbox.enqueue({'type': 'command'}, (e) => sends.add(e));

        async.elapse(const Duration(milliseconds: 500)); // attempt 1
        expect(sends, hasLength(2));

        // Simulated reconnect — flush resends the queue right now.
        outbox.flush();
        expect(sends, hasLength(3));

        // The reset budget means it can retry again instead of being dropped.
        async.elapse(const Duration(milliseconds: 500));
        expect(sends, hasLength(4));
        expect(outbox.isDegraded.value, isFalse);
        outbox.dispose();
      });
    });
  });

  group('AckOutbox — clearByType', () {
    test('drops pending messages of a type (interrupt_ack has no id)', () {
      final outbox = AckOutbox();
      outbox.enqueue({'type': 'interrupt'}, (_) {});
      outbox.enqueue({'type': 'input.multimodal', 'content': 'x'}, (_) {});

      outbox.clearByType('interrupt');
      expect(outbox.pendingCount, 1);
      expect(outbox.hasPending, isTrue);
      outbox.dispose();
    });
  });
}

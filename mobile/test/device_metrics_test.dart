import 'package:aariya_mobile/core/services/device_metrics.dart';
import 'package:fake_async/fake_async.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('DeviceMetricsReporter', () {
    test('sends an immediate frame on start(), then on every interval', () {
      fakeAsync((async) {
        final frames = <Map<String, dynamic>>[];
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 10),
          collector: () async => {
            'platform': 'android',
            'battery': 87,
            'charging': true,
            'cpu_percent': 12.5,
            'ram_percent': 61.0,
            'model': 'Pixel 7',
          },
          send: (frame) => frames.add(frame),
        );

        reporter.start();
        async.flushMicrotasks(); // immediate sample

        expect(frames, hasLength(1));
        expect(frames.single['type'], 'device_metrics');
        expect((frames.single['device'] as Map)['battery'], 87);
        expect((frames.single['device'] as Map)['cpu_percent'], 12.5);
        expect(frames.single['ts'], isA<num>());

        async.elapse(const Duration(seconds: 10));
        expect(frames, hasLength(2));
        async.elapse(const Duration(seconds: 20));
        expect(frames, hasLength(4));
        reporter.stop();
      });
    });

    test('empty collector result is skipped (no empty frames)', () {
      fakeAsync((async) {
        final frames = <Map<String, dynamic>>[];
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 5),
          collector: () async => <String, dynamic>{},
          send: (frame) => frames.add(frame),
        );

        reporter.start();
        async.flushMicrotasks();
        async.elapse(const Duration(seconds: 15));

        expect(frames, isEmpty);
        reporter.stop();
      });
    });

    test('collector errors are swallowed — the loop keeps running', () {
      fakeAsync((async) {
        final frames = <Map<String, dynamic>>[];
        var calls = 0;
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 5),
          collector: () async {
            calls++;
            if (calls == 1) throw StateError('battery API exploded');
            return {'battery': 50};
          },
          send: (frame) => frames.add(frame),
        );

        reporter.start();
        async.flushMicrotasks(); // first tick throws — no frame
        expect(frames, isEmpty);

        async.elapse(const Duration(seconds: 5)); // second tick recovers
        expect(frames, hasLength(1));
        expect((frames.single['device'] as Map)['battery'], 50);
        reporter.stop();
      });
    });

    test('stop() halts periodic reporting', () {
      fakeAsync((async) {
        final frames = <Map<String, dynamic>>[];
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 5),
          collector: () async => {'battery': 42},
          send: (frame) => frames.add(frame),
        );

        reporter.start();
        async.flushMicrotasks();
        expect(frames, hasLength(1));

        reporter.stop();
        async.elapse(const Duration(seconds: 30));
        expect(frames, hasLength(1)); // no further ticks
      });
    });

    test('start() is idempotent', () {
      fakeAsync((async) {
        final frames = <Map<String, dynamic>>[];
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 5),
          collector: () async => {'battery': 1},
          send: (frame) => frames.add(frame),
        );

        reporter.start();
        reporter.start();
        async.flushMicrotasks();

        // One immediate sample, one timer — never duplicated.
        expect(frames, hasLength(1));
        async.elapse(const Duration(seconds: 5));
        expect(frames, hasLength(2));
        reporter.stop();
      });
    });
  });
}

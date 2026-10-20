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

    // ── On-device UI feed (Analytics → "THIS DEVICE") ────────────────────────
    test('latest publishes each sample for the analytics screen', () {
      fakeAsync((async) {
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 10),
          collector: () async => {
            'platform': 'android',
            'battery': 72,
            'charging': true,
            'cpu_percent': 18.4,
            'ram_percent': 57.6,
            'ram_used_gb': 6.31,
            'ram_total_gb': 10.95,
            'model': 'NE2215',
            'manufacturer': 'OnePlus',
            'os_version': 'Android 15',
          },
          send: (_) {},
        );

        reporter.start();
        async.flushMicrotasks();

        expect(reporter.latest.value['battery'], 72);
        expect(reporter.latest.value['cpu_percent'], 18.4);
        expect(reporter.latest.value['model'], 'NE2215');
        // Unmodifiable — a UI listener must not be able to mutate the sample.
        expect(
          () => reporter.latest.value['battery'] = 0,
          throwsUnsupportedError,
        );
        reporter.stop();
      });
    });

    test('latest keeps the last good sample when a tick comes back empty', () {
      fakeAsync((async) {
        var calls = 0;
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 5),
          collector: () async =>
              ++calls == 1 ? {'battery': 55} : <String, dynamic>{},
          send: (_) {},
        );

        reporter.start();
        async.flushMicrotasks();
        expect(reporter.latest.value['battery'], 55);

        async.elapse(const Duration(seconds: 5)); // empty sample is skipped
        expect(reporter.latest.value['battery'], 55);
        reporter.stop();
      });
    });

    test('latest updates even when the socket send throws (offline)', () {
      fakeAsync((async) {
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 5),
          collector: () async => {'battery': 63},
          send: (_) => throw StateError('socket closed'),
        );

        reporter.start();
        async.flushMicrotasks();

        // Local stats are most useful precisely when the link is down.
        expect(reporter.latest.value['battery'], 63);
        reporter.stop();
      });
    });

    test('samples for the UI between telemetry sends', () {
      fakeAsync((async) {
        final frames = <Map<String, dynamic>>[];
        var sample = 0;
        final reporter = DeviceMetricsReporter(
          interval: const Duration(seconds: 10),
          sampleInterval: const Duration(seconds: 2),
          collector: () async => {'battery': ++sample},
          send: (frame) => frames.add(frame),
        );

        reporter.start();
        async.flushMicrotasks();

        expect(frames, hasLength(1)); // immediate sample is also transmitted
        expect(reporter.latest.value['battery'], 1);

        // t=2s: UI-only sample. The card moves, the wire stays quiet.
        async.elapse(const Duration(seconds: 2));
        expect(reporter.latest.value['battery'], 2);
        expect(frames, hasLength(1));

        // t=10s: the telemetry tick transmits again.
        async.elapse(const Duration(seconds: 8));
        expect(frames, hasLength(2));
        expect(reporter.latest.value['battery'], greaterThan(2));

        // stop() must silence the local sampler too, not just the sender.
        reporter.stop();
        final last = reporter.latest.value['battery'];
        async.elapse(const Duration(seconds: 30));
        expect(reporter.latest.value['battery'], last);
        expect(frames, hasLength(2));
      });
    });
  });
}

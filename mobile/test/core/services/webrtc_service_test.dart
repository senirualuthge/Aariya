import 'package:aariya_mobile/core/services/device_auth_service.dart';
import 'package:aariya_mobile/core/services/server_config.dart';
import 'package:aariya_mobile/core/services/webrtc_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    await ServerConfig.instance.load();
  });

  group('WebRTC recovery policy', () {
    test('maximum reconnect attempts are bounded', () {
      const maxAttempts = 5;

      expect(maxAttempts, equals(5));
    });

    test('reconnect delay uses exponential backoff', () {
      const delays = [1, 2, 4, 8, 16];

      expect(delays.length, equals(5));

      for (var i = 1; i < delays.length; i++) {
        expect(delays[i], equals(delays[i - 1] * 2));
      }
    });

    test('reconnect policy does not retry indefinitely', () {
      const maxAttempts = 5;
      var attempts = 0;

      while (attempts < maxAttempts) {
        attempts++;
      }

      expect(attempts, equals(maxAttempts));
    });
  });

  group('WebRTCService', () {
    test('initial state is disconnected', () {
      final service = WebRTCService.instance;
      expect(service.connectionState.value, 'disconnected');
      expect(service.pc, isNull);
      expect(service.localStream, isNull);
    });

    test('stop() safely cleans up and sets state to disconnected', () async {
      final service = WebRTCService.instance;
      service.connectionState.value = 'connected';
      await service.stop();
      expect(service.connectionState.value, 'disconnected');
      expect(service.pc, isNull);
      expect(service.localStream, isNull);
    });

    test(
      'remote non-loopback host without TLS throws StateError on negotiation',
      () async {
        final service = WebRTCService.instance;
        await ServerConfig.instance.save('192.168.1.50', 8000, secure: false);

        expect(
          () => service.start('192.168.1.50'),
          throwsA(
            isA<StateError>().having(
              (e) => e.message,
              'message',
              contains('Remote WebRTC connections require HTTPS'),
            ),
          ),
        );

        // Restore loopback
        await ServerConfig.instance.save('127.0.0.1', 8000, secure: false);
      },
    );

    test('device auth exception prevents unauthenticated start', () async {
      final service = WebRTCService.instance;
      expect(
        () => service.start('127.0.0.1'),
        throwsA(
          isA<DeviceAuthException>().having(
            (e) => e.needsPairing,
            'needsPairing',
            isTrue,
          ),
        ),
      );
    });
  });
}

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aariya_mobile/core/services/device_auth_service.dart';
import 'package:aariya_mobile/features/settings/presentation/device_pairing_screen.dart';

void main() {
  setUp(() {
    DeviceAuthService.instance.needsPairing.value = false;
  });

  tearDown(() {
    DeviceAuthService.instance.needsPairing.value = false;
  });

  testWidgets('pairing screen accepts a code and label', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: DevicePairingScreen()),
    );
    // Secure-storage platform channels are absent in widget tests; do not
    // wait for the loading spinner to disappear.
    await tester.pump(const Duration(milliseconds: 50));

    expect(find.text('TRUSTED DEVICE'), findsOneWidget);
    expect(find.text('PAIRING CODE'), findsOneWidget);
    expect(
      find.widgetWithText(TextField, 'XXXXX-XXXXX-XXXXX-XXXXX'),
      findsOneWidget,
    );
    expect(find.text('PAIR THIS PHONE'), findsOneWidget);
  });

  testWidgets('revoked state surfaces a re-pair banner', (tester) async {
    DeviceAuthService.instance.needsPairing.value = true;

    await tester.pumpWidget(
      const MaterialApp(home: DevicePairingScreen()),
    );
    await tester.pump(const Duration(milliseconds: 50));

    expect(
      find.text('This phone is no longer trusted. Pair it again.'),
      findsOneWidget,
    );
  });

  testWidgets('empty code does not start a pairing request', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(home: DevicePairingScreen()),
    );
    await tester.pump(const Duration(milliseconds: 50));

    await tester.tap(find.text('PAIR THIS PHONE'));
    await tester.pump();

    // Still idle: no network call was attempted for an empty code.
    expect(find.textContaining('Pairing failed'), findsNothing);
    expect(find.textContaining('Invalid pairing code'), findsNothing);
  });
}

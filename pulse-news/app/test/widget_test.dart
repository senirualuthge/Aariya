import 'package:flutter_test/flutter_test.dart';

import 'package:app/main.dart';

void main() {
  test('App class can be instantiated', () {
    expect(PulseNewsApp, isNotNull);
    const app = PulseNewsApp();
    expect(app, isA<PulseNewsApp>());
    expect((app as dynamic).key, isNull);
  });

  test('MainShell class exists', () {
    expect(MainShell, isNotNull);
  });
}

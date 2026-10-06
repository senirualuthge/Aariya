import 'package:aariya_mobile/core/services/server_config.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// The backend counts connected DEVICES, not sockets, and it can only do that
/// because every channel of one phone announces the same id. These tests pin
/// the two properties that make the id usable: it is never empty, and it is
/// stable across the app's channels and relaunches.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('client id is generated lazily, stays stable, and is persisted', () async {
    SharedPreferences.setMockInitialValues({});
    final config = ServerConfig.instance;

    // Readable before load() so a connect() that races bootstrap still tags
    // its channels — an empty id would make the backend count sockets again.
    final generated = config.clientId;
    expect(generated, isNotEmpty);
    expect(config.clientId, generated, reason: 'stable within a session');

    await config.load();
    expect(config.clientId, generated, reason: 'load() must not mint a new id');

    final prefs = await SharedPreferences.getInstance();
    expect(
      prefs.getString('client_id'),
      generated,
      reason: 'persisted so the next launch is still the same device',
    );
  });
}
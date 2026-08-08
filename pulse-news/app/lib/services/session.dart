import 'dart:math';

class Session {
  static final Session _instance = Session._();
  static Session get instance => _instance;
  Session._();

  late final String userId;

  void init() {
    final rand = Random();
    final ts = DateTime.now().microsecondsSinceEpoch;
    userId = 'anon-${ts.toRadixString(36)}-${rand.nextInt(99999).toRadixString(36)}';
  }
}

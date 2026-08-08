class ApiConfig {
  static const String _defaultHost = 'localhost';
  static const int _defaultPort = 8001;

  static String get baseUrl {
    const host = String.fromEnvironment('PULSE_HOST', defaultValue: _defaultHost);
    const port = String.fromEnvironment('PULSE_PORT', defaultValue: '$_defaultPort');
    return 'http://$host:$port';
  }

  static String get wsUrl {
    const host = String.fromEnvironment('PULSE_HOST', defaultValue: _defaultHost);
    const port = String.fromEnvironment('PULSE_PORT', defaultValue: '$_defaultPort');
    return 'ws://$host:$port/ws/feed';
  }
}

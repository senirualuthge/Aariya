import 'package:flutter/material.dart';
import 'app/app.dart';
import 'services/device_metrics.dart';
import 'services/server_config.dart';
import 'services/websocket_service.dart';

Future<void> bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Load persisted server address before opening any sockets.
  await ServerConfig.instance.load();

  // Wait for the websocket service to initialize before starting the app
  await WebSocketService.instance.connect();

  // Report the phone's own battery / CPU / memory to the backend so the
  // analytics dashboard's System Health → Mobile App panel can show them.
  DeviceMetricsReporter.instance.start();

  runApp(const App());
}

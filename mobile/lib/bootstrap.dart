import 'package:flutter/material.dart';
import 'app/app.dart';
import 'services/server_config.dart';
import 'services/websocket_service.dart';

Future<void> bootstrap() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Load persisted server address before opening any sockets.
  await ServerConfig.instance.load();

  // Wait for the websocket service to initialize before starting the app
  await WebSocketService.instance.connect();
  runApp(const App());
}

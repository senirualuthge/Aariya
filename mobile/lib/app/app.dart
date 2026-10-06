import 'package:flutter/material.dart';
import 'theme.dart';
import '../features/chat/presentation/chat_screen.dart';
import '../features/analytics/presentation/analytics_screen.dart';
import '../features/companion/presentation/companion_screen.dart';
import '../core/services/websocket_service.dart';
import '../core/services/connection_monitor.dart';

class App extends StatefulWidget {
  const App({super.key});

  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> {
  int _currentIndex = 0;

  final List<Widget> _screens = const [
    ChatScreen(),
    AnalyticsScreen(),
    CompanionScreen(),
  ];

  @override
  void initState() {
    super.initState();
    // Connect all channels then start health monitoring
    WebSocketService.instance.connect().then((_) {
      ConnectionMonitor.instance.start();
    });
  }

  @override
  void dispose() {
    ConnectionMonitor.instance.dispose();
    WebSocketService.instance.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Aariya',
      debugShowCheckedModeBanner: false,
      theme: appTheme,
      home: Scaffold(
        body: IndexedStack(
          index: _currentIndex,
          children: _screens,
        ),
        bottomNavigationBar: BottomNavigationBar(
          currentIndex: _currentIndex,
          // Colors come from appTheme.bottomNavigationBarTheme
          onTap: (index) => setState(() => _currentIndex = index),
          items: const [
            BottomNavigationBarItem(
              icon: Icon(Icons.chat_bubble_outline),
              label: 'Chat',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.analytics_outlined),
              label: 'Analytics',
            ),
            BottomNavigationBarItem(
              icon: Icon(Icons.favorite_outline),
              label: 'Companion',
            ),
          ],
        ),
      ),
    );
  }
}

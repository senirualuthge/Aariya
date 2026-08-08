import 'package:flutter/material.dart';

final appTheme = ThemeData(
  useMaterial3: true,
  brightness: Brightness.dark,
  // Cosmic orb palette (matches aariya-circular-orb.html)
  colorScheme: const ColorScheme.dark(
    primary: Color(0xFF7C5CFF),
    secondary: Color(0xFF33E6FF),
    surface: Color(0xFF0A0B14),
  ),
  primaryColor: const Color(0xFF7C5CFF),
  scaffoldBackgroundColor: const Color(0xFF020203),
  appBarTheme: const AppBarTheme(
    backgroundColor: Color(0xFF0A0B14),
    elevation: 0,
    centerTitle: true,
  ),
  bottomNavigationBarTheme: const BottomNavigationBarThemeData(
    backgroundColor: Color(0xFF0A0B14),
    selectedItemColor: Color(0xFF7C5CFF),
    unselectedItemColor: Colors.white24,
  ),
);

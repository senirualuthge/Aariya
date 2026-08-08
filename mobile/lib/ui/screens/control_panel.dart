import 'package:flutter/material.dart';

/// Control-layer authority sheet.
///
/// Resolves the `*Mobile Achi v2.txt` zero-interference contradiction:
/// mobile is the CONTROL layer, the laptop dashboard is the AUTHORITY
/// layer. Destructive / identity-mutating commands (`wipe_memory`,
/// `set_personality`, `override_mode`, `force_mode`) are rejected by the
/// server (`server/systems/security/mobile_authority.py`) and therefore
/// shown here as **laptop-dashboard-only** — the phone cannot issue them.
class ControlPanelBottomSheet extends StatelessWidget {
  const ControlPanelBottomSheet({super.key});

  static void show(BuildContext context) {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF0F172A),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (context) => const ControlPanelBottomSheet(),
    );
  }

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.all(24.0),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.admin_panel_settings, color: Colors.cyanAccent),
              SizedBox(width: 8),
              Text(
                'CONTROL LAYER',
                style: TextStyle(
                  color: Colors.cyanAccent,
                  fontSize: 14,
                  letterSpacing: 2.0,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ],
          ),
          SizedBox(height: 8),
          Text(
            'Your phone is the remote control. Commands that rewrite '
            'memory or personality are reserved for the laptop dashboard '
            '(the authority layer) and are blocked here.',
            style: TextStyle(color: Colors.white70, fontSize: 13, height: 1.4),
          ),
          SizedBox(height: 24),

          _AuthorityOnlyTile(
            icon: Icons.memory,
            color: Colors.redAccent,
            title: 'Wipe Core Memory',
            subtitle: 'Laptop dashboard only — deletes conversational hierarchy',
          ),
          Divider(color: Colors.white10),
          _AuthorityOnlyTile(
            icon: Icons.psychology,
            color: Colors.orangeAccent,
            title: 'Enforce Focus Mode',
            subtitle: 'Laptop dashboard only — overrides RL behaviour policy',
          ),
          Divider(color: Colors.white10),
          _AuthorityOnlyTile(
            icon: Icons.theater_comedy,
            color: Colors.greenAccent,
            title: 'Change Personality',
            subtitle: 'Laptop dashboard only — rewrites the persona vector',
          ),
          SizedBox(height: 16),

          // What the phone CAN do from here.
          Row(
            children: [
              Icon(Icons.mic_none, size: 18, color: Colors.white38),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Your phone can still talk to Aariya, interrupt her, '
                  'and watch her state live — those flow through the chat '
                  'channel and are unaffected.',
                  style: TextStyle(color: Colors.white54, fontSize: 12, height: 1.4),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _AuthorityOnlyTile extends StatelessWidget {
  const _AuthorityOnlyTile({
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
  });

  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: 0.55,
      child: ListTile(
        contentPadding: EdgeInsets.zero,
        leading: Icon(icon, color: color),
        title: Text(title, style: const TextStyle(color: Colors.white)),
        subtitle: Text(
          subtitle,
          style: const TextStyle(color: Colors.white60, fontSize: 12),
        ),
        trailing: const Icon(Icons.lock_outline,
            color: Colors.white38, size: 18),
      ),
    );
  }
}

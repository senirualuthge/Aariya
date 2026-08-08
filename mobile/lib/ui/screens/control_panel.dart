import 'package:flutter/material.dart';
import '../../brain/client_brain.dart';

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

  void _dispatchCommand(BuildContext context, String action, [Map<String, dynamic>? data]) {
    ClientBrain.instance.sendRemoteCommand(action, data);
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('Command dispatched: $action'),
        backgroundColor: Colors.cyan.shade800,
        behavior: SnackBarBehavior.floating,
      ),
    );
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(24.0),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'REMOTE OVERRIDE',
            style: TextStyle(
              color: Colors.cyanAccent,
              fontSize: 14,
              letterSpacing: 2.0,
              fontWeight: FontWeight.bold,
            ),
          ),
          const SizedBox(height: 24),
          
          ListTile(
            leading: const Icon(Icons.memory, color: Colors.redAccent),
            title: const Text('Wipe Core Memory', style: TextStyle(color: Colors.white)),
            subtitle: const Text('Deletes current short-term and conversational hierarchy', style: TextStyle(color: Colors.white60, fontSize: 12)),
            onTap: () => _dispatchCommand(context, 'wipe_memory'),
          ),
          
          const Divider(color: Colors.white10),
          
          ListTile(
            leading: const Icon(Icons.psychology, color: Colors.orangeAccent),
            title: const Text('Enforce Focus Mode', style: TextStyle(color: Colors.white)),
            subtitle: const Text('Overrides current RL policy to strict reasoning', style: TextStyle(color: Colors.white60, fontSize: 12)),
            onTap: () => _dispatchCommand(context, 'override_mode', {'mode': 'focus'}),
          ),
          
          const Divider(color: Colors.white10),
          
          ListTile(
            leading: const Icon(Icons.theater_comedy, color: Colors.greenAccent),
            title: const Text('Change Personality (Playful)', style: TextStyle(color: Colors.white)),
            subtitle: const Text('Modifies the persona vector live', style: TextStyle(color: Colors.white60, fontSize: 12)),
            onTap: () => _dispatchCommand(context, 'set_personality', {'persona': 'playful'}),
          ),
        ],
      ),
    );
  }
}

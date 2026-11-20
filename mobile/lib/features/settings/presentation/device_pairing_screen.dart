import 'package:flutter/material.dart';

import '../../../core/services/device_auth_service.dart';
import '../../../core/services/websocket_service.dart';

/// Pair this phone as a trusted Aariya device.
///
/// The code is created on the server machine (never over HTTP):
///
///   python -m server.tools.create_device_pairing_code --role mobile
///
/// It expires after five minutes and works once. The returned credential is
/// kept in Android Keystore / iOS Keychain by [DeviceAuthService].
class DevicePairingScreen extends StatefulWidget {
  const DevicePairingScreen({super.key});

  static Future<void> show(BuildContext context) {
    return Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => const DevicePairingScreen(),
      ),
    );
  }

  @override
  State<DevicePairingScreen> createState() => _DevicePairingScreenState();
}

class _DevicePairingScreenState extends State<DevicePairingScreen> {
  final TextEditingController _codeCtrl = TextEditingController();
  final TextEditingController _labelCtrl =
      TextEditingController(text: 'this phone');

  DeviceIdentity? _identity;
  bool _loading = true;
  bool _pairing = false;
  String? _error;
  String? _success;

  @override
  void initState() {
    super.initState();
    _loadIdentity();
  }

  @override
  void dispose() {
    _codeCtrl.dispose();
    _labelCtrl.dispose();
    super.dispose();
  }

  Future<void> _loadIdentity() async {
    DeviceIdentity? identity;
    try {
      identity = await DeviceAuthService.instance.me();
    } on DeviceAuthException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) setState(() => _error = 'Could not read device identity');
      debugPrint('[Pairing] identity load failed: $e');
    }
    if (!mounted) return;
    setState(() {
      _identity = identity;
      _loading = false;
    });
  }

  Future<void> _pair() async {
    final code = _codeCtrl.text.trim();
    if (code.isEmpty || _pairing) return;

    setState(() {
      _pairing = true;
      _error = null;
      _success = null;
    });

    try {
      final identity = await DeviceAuthService.instance.pair(
        pairingCode: code,
        label: _labelCtrl.text.trim(),
      );
      if (!mounted) return;

      setState(() {
        _identity = identity;
        _success = 'Paired as ${identity.label} · ${identity.role}';
      });
      _codeCtrl.clear();

      // Re-open the chat/control/analytics sockets with device tickets.
      await WebSocketService.instance.reconnectToNewServer();
    } on DeviceAuthException catch (e) {
      if (mounted) setState(() => _error = e.message);
    } catch (e) {
      if (mounted) setState(() => _error = 'Pairing failed: $e');
    } finally {
      if (mounted) setState(() => _pairing = false);
    }
  }

  Future<void> _forget() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: const Color(0xFF0F172A),
        title: const Text('Forget this device?'),
        content: const Text(
          'The credential is removed from this phone. You will need a new '
          'pairing code to connect to a device-auth server again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: FilledButton.styleFrom(backgroundColor: Colors.redAccent),
            child: const Text('Forget'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    await DeviceAuthService.instance.clear();
    if (!mounted) return;
    setState(() {
      _identity = null;
      _success = null;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF070B14),
      appBar: AppBar(
        backgroundColor: const Color(0xFF0F172A),
        title: const Text('TRUSTED DEVICE'),
        centerTitle: false,
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            ValueListenableBuilder<bool>(
              valueListenable: DeviceAuthService.instance.needsPairing,
              builder: (context, needsPairing, _) {
                if (!needsPairing && _identity != null) {
                  return const SizedBox.shrink();
                }
                return Container(
                  margin: const EdgeInsets.only(bottom: 18),
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: (needsPairing ? Colors.redAccent : Colors.cyan)
                        .withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(
                      color: (needsPairing ? Colors.redAccent : Colors.cyan)
                          .withValues(alpha: 0.45),
                    ),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        needsPairing
                            ? Icons.gpp_bad_outlined
                            : Icons.phonelink_lock,
                        color: needsPairing
                            ? Colors.redAccent
                            : Colors.cyanAccent,
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          needsPairing
                              ? 'This phone is no longer trusted. Pair it again.'
                              : 'This phone is not paired yet. Enter a code '
                                  'created on the server.',
                          style: const TextStyle(color: Colors.white70),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
            if (_loading)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: CircularProgressIndicator(color: Colors.cyanAccent),
                ),
              )
            else if (_identity != null) ...[
              _IdentityCard(identity: _identity!),
              const SizedBox(height: 18),
              OutlinedButton.icon(
                onPressed: _forget,
                style: OutlinedButton.styleFrom(
                  foregroundColor: Colors.redAccent,
                  side: const BorderSide(color: Colors.redAccent),
                  padding: const EdgeInsets.symmetric(vertical: 14),
                ),
                icon: const Icon(Icons.link_off),
                label: const Text('Forget this device'),
              ),
              const SizedBox(height: 24),
              const Divider(color: Colors.white12),
              const SizedBox(height: 12),
              const Text(
                'PAIR A DIFFERENT CODE',
                style: TextStyle(
                  color: Colors.white38,
                  fontSize: 11,
                  letterSpacing: 1.5,
                ),
              ),
              const SizedBox(height: 12),
            ],
            const Text(
              'PAIRING CODE',
              style: TextStyle(
                color: Colors.cyanAccent,
                fontSize: 13,
                letterSpacing: 2,
                fontWeight: FontWeight.bold,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'On the server machine:\n'
              'python -m server.tools.create_device_pairing_code --role mobile',
              style: TextStyle(color: Colors.white38, fontSize: 12),
            ),
            const SizedBox(height: 18),
            TextField(
              controller: _codeCtrl,
              autocorrect: false,
              enableSuggestions: false,
              textCapitalization: TextCapitalization.characters,
              style: const TextStyle(
                color: Colors.white,
                letterSpacing: 3,
                fontSize: 18,
              ),
              decoration: _decoration(
                label: 'Code',
                hint: 'XXXXX-XXXXX-XXXXX-XXXXX',
                icon: Icons.key_outlined,
              ),
              onSubmitted: (_) => _pair(),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: _labelCtrl,
              style: const TextStyle(color: Colors.white),
              decoration: _decoration(
                label: 'Device label',
                hint: 'this phone',
                icon: Icons.smartphone,
              ),
            ),
            const SizedBox(height: 20),
            FilledButton(
              onPressed: _pairing ? null : _pair,
              style: FilledButton.styleFrom(
                backgroundColor: Colors.cyan.shade700,
                foregroundColor: Colors.white,
                padding: const EdgeInsets.symmetric(vertical: 15),
              ),
              child: _pairing
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: Colors.white,
                      ),
                    )
                  : const Text('PAIR THIS PHONE'),
            ),
            const SizedBox(height: 10),
            const Text(
              'Codes expire after five minutes and work once. This phone and '
              'your computer resolve to the same owner; neither can choose '
              'another person\'s memories with a URL.',
              style: TextStyle(color: Colors.white30, fontSize: 11),
            ),
            if (_success != null) ...[
              const SizedBox(height: 16),
              Text(
                _success!,
                style: const TextStyle(color: Colors.greenAccent, fontSize: 13),
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 16),
              Text(
                _error!,
                style: const TextStyle(color: Colors.redAccent, fontSize: 13),
              ),
            ],
          ],
        ),
      ),
    );
  }

  InputDecoration _decoration({
    required String label,
    required String hint,
    required IconData icon,
  }) {
    return InputDecoration(
      labelText: label,
      labelStyle: const TextStyle(color: Colors.white38),
      hintText: hint,
      hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.25)),
      prefixIcon: Icon(icon, color: Colors.cyanAccent, size: 20),
      filled: true,
      fillColor: Colors.white.withValues(alpha: 0.05),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(12),
        borderSide: BorderSide(color: Colors.cyanAccent.withValues(alpha: 0.5)),
      ),
    );
  }
}

class _IdentityCard extends StatelessWidget {
  const _IdentityCard({required this.identity});

  final DeviceIdentity identity;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.greenAccent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: Colors.greenAccent.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            children: [
              Icon(Icons.verified_user, color: Colors.greenAccent, size: 18),
              SizedBox(width: 8),
              Text(
                'PAIRED',
                style: TextStyle(
                  color: Colors.greenAccent,
                  fontWeight: FontWeight.bold,
                  letterSpacing: 1.2,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Text(
            '${identity.label} · ${identity.role}',
            style: const TextStyle(color: Colors.white, fontSize: 15),
          ),
          const SizedBox(height: 4),
          Text(
            'owner ${identity.ownerId}  ·  device ${identity.deviceId}',
            style: const TextStyle(color: Colors.white38, fontSize: 11),
          ),
        ],
      ),
    );
  }
}

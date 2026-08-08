import 'package:flutter/material.dart';
import 'package:speech_to_text/speech_to_text.dart';
import 'package:permission_handler/permission_handler.dart';
import '../../state/chat_controller.dart';
import '../../services/connection_monitor.dart';
import '../../services/server_config.dart';
import '../../services/websocket_service.dart';
import '../widgets/voice_conversation_overlay.dart';
import 'control_panel.dart';
import 'server_settings_sheet.dart';

class ChatScreen extends StatefulWidget {
  const ChatScreen({super.key});

  @override
  State<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends State<ChatScreen> {
  final TextEditingController _controller = TextEditingController();
  final ScrollController _scrollController = ScrollController();
  late final ChatController _chatController;

  final SpeechToText _speechToText = SpeechToText();

  @override
  void initState() {
    super.initState();
    _chatController = ChatController.instance;
    _initSpeech();
  }

  void _initSpeech() async {
    await _speechToText.initialize();
  }

  void _openConversationMode({bool startWithCamera = false}) async {
    var status = await Permission.microphone.request();
    if (status != PermissionStatus.granted) return;

    if (!mounted) return;

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      isDismissible: false,
      enableDrag: false,
      backgroundColor: Colors.transparent,
      builder: (context) => VoiceConversationOverlay(
        chatController: _chatController,
        speechToText: _speechToText,
        startWithCamera: startWithCamera,
      ),
    );
  }

  @override
  void dispose() {
    _controller.dispose();
    _scrollController.dispose();
    super.dispose();
  }

  void _sendMessage() {
    if (_controller.text.trim().isNotEmpty) {
      _chatController.sendMessage(_controller.text.trim());
      _controller.clear();
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Column(
          children: [
            const Text('Aariya', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            // Live emotion + connection subtitle instead of hardcoded "Calm".
            ValueListenableBuilder<ConnectionQuality>(
              valueListenable: ConnectionMonitor.instance.quality,
              builder: (context, quality, child) {
                final (label, color) = switch (quality) {
                  ConnectionQuality.excellent => ('● LIVE', Colors.greenAccent),
                  ConnectionQuality.good      => ('● GOOD', Colors.tealAccent),
                  ConnectionQuality.degraded  => ('● SLOW', Colors.orangeAccent),
                  ConnectionQuality.offline   => ('○ OFFLINE', Colors.redAccent),
                };
                return AnimatedBuilder(
                  animation: _chatController.brain,
                  builder: (context, _) {
                    final emotion = _chatController.brain.emotion;
                    final subtitle = quality == ConnectionQuality.offline
                        ? '○ Offline'
                        : '$label  ·  ${emotion.isEmpty ? 'calm' : emotion}';
                    return Text(
                      subtitle,
                      style: TextStyle(
                        fontSize: 12,
                        color: color,
                        fontWeight: FontWeight.w500,
                      ),
                    );
                  },
                );
              },
            ),
          ],
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.settings_outlined, color: Colors.cyanAccent),
            tooltip: 'Server Settings',
            onPressed: () => ServerSettingsSheet.show(context),
          ),
          IconButton(
            icon: const Icon(Icons.tune, color: Colors.cyanAccent),
            tooltip: 'Remote Control',
            onPressed: () => ControlPanelBottomSheet.show(context),
          ),
        ],
      ),
      body: Stack(
        children: [
          Column(
            children: [
              // Chat Log Area
              Expanded(
                child: AnimatedBuilder(
                  animation: _chatController,
                  builder: (context, _) {
                    final messages = _chatController.messages;
                    // Auto-scroll to the newest message as it arrives.
                    _scrollToBottom();

                    if (messages.isEmpty) {
                      return const _EmptyChatState();
                    }

                    return ListView.builder(
                      controller: _scrollController,
                      padding: const EdgeInsets.all(16),
                      itemCount: messages.length + (_chatController.isThinking ? 1 : 0),
                      itemBuilder: (context, index) {
                        if (index == messages.length) {
                          return const _ThinkingBubble();
                        }
                        final msg = messages[index];
                        return Align(
                          alignment: msg.isUser ? Alignment.centerRight : Alignment.centerLeft,
                          child: ContainerCard(
                            text: msg.text,
                            isUser: msg.isUser,
                            emotion: msg.emotion,
                            timestamp: msg.timestamp,
                          ),
                        );
                      },
                    );
                  },
                ),
              ),

              // Interaction Bar
              Padding(
                padding: const EdgeInsets.all(16.0),
                child: Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: _controller,
                        style: const TextStyle(color: Colors.white),
                        decoration: InputDecoration(
                          hintText: "Message Aariya...",
                          hintStyle: TextStyle(color: Colors.white.withValues(alpha: 0.5)),
                          filled: true,
                          fillColor: Colors.black.withValues(alpha: 0.25),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(30),
                            borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1), width: 1),
                          ),
                          enabledBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(30),
                            borderSide: BorderSide(color: Colors.white.withValues(alpha: 0.1), width: 1),
                          ),
                          focusedBorder: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(30),
                            borderSide: BorderSide(color: Colors.cyanAccent.withValues(alpha: 0.5), width: 1),
                          ),
                          contentPadding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
                          suffixIcon: IconButton(
                            icon: const Icon(Icons.send, color: Colors.cyanAccent, size: 20),
                            onPressed: _sendMessage,
                          ),
                        ),
                        onSubmitted: (_) => _sendMessage(),
                      ),
                    ),
                    const SizedBox(width: 12),
                    GestureDetector(
                      onTap: () => _openConversationMode(startWithCamera: false),
                      child: Container(
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: Theme.of(context).primaryColor,
                          boxShadow: [
                            BoxShadow(color: Theme.of(context).primaryColor.withValues(alpha: 0.4), blurRadius: 8, offset: const Offset(0, 4))
                          ]
                        ),
                        child: const Icon(Icons.mic, color: Colors.white, size: 24),
                      ),
                    ),
                    const SizedBox(width: 12),
                    GestureDetector(
                      onTap: () => _openConversationMode(startWithCamera: true),
                      child: Container(
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          shape: BoxShape.circle,
                          color: Colors.greenAccent.withValues(alpha: 0.8),
                          boxShadow: [
                            BoxShadow(color: Colors.greenAccent.withValues(alpha: 0.3), blurRadius: 8, offset: const Offset(0, 4))
                          ]
                        ),
                        child: const Icon(Icons.videocam, color: Colors.black87, size: 24),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),

          // Disconnected Banner
          ValueListenableBuilder<bool>(
            valueListenable: WebSocketService.instance.isConnected,
            builder: (context, connected, child) {
              if (connected) return const SizedBox.shrink();

              return Positioned(
                top: 0,
                left: 0,
                right: 0,
                child: Container(
                  color: Colors.redAccent.withValues(alpha: 0.9),
                  padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 16),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.wifi_off, color: Colors.white, size: 16),
                          SizedBox(width: 8),
                          Text(
                            "Not connected — auto-reconnecting",
                            style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold),
                          ),
                        ],
                      ),
                      const SizedBox(height: 2),
                      ValueListenableBuilder<ConnectionQuality>(
                        valueListenable: ConnectionMonitor.instance.quality,
                        builder: (context, quality, _) {
                          final target = quality == ConnectionQuality.degraded
                              ? '${ServerConfig.instance.host}:${ServerConfig.instance.port}'
                              : ServerConfig.instance.host;
                          return Text(
                            target,
                            style: const TextStyle(color: Colors.white70, fontSize: 11),
                          );
                        },
                      ),
                    ],
                  ),
                ),
              );
            },
          ),
        ],
      ),
    );
  }
}

class ContainerCard extends StatelessWidget {
  final String text;
  final bool isUser;
  final String? emotion;
  final int timestamp;

  const ContainerCard({
    super.key,
    required this.text,
    required this.isUser,
    this.emotion,
    this.timestamp = 0,
  });

  String _formatTime(int ts) {
    if (ts <= 0) return '';
    final dt = DateTime.fromMillisecondsSinceEpoch(ts);
    final hh = dt.hour.toString().padLeft(2, '0');
    final mm = dt.minute.toString().padLeft(2, '0');
    return '$hh:$mm';
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.symmetric(vertical: 4),
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      decoration: BoxDecoration(
        color: isUser ? Theme.of(context).primaryColor : Colors.blueGrey.withValues(alpha: 0.3),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Column(
        crossAxisAlignment: isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          Text(text, style: const TextStyle(fontSize: 16)),
          if (!isUser && emotion != null && emotion!.isNotEmpty) ...[
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(10),
              ),
              child: Text(
                emotion!,
                style: TextStyle(
                  fontSize: 11,
                  color: Colors.cyanAccent.withValues(alpha: 0.8),
                ),
              ),
            ),
          ],
          if (timestamp > 0) ...[
            const SizedBox(height: 4),
            Text(
              _formatTime(timestamp),
              style: TextStyle(
                fontSize: 10,
                color: Colors.white.withValues(alpha: 0.35),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Empty-state shown before the first exchange.
class _EmptyChatState extends StatelessWidget {
  const _EmptyChatState();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.blur_circular, size: 56, color: Colors.white.withValues(alpha: 0.08)),
          const SizedBox(height: 16),
          Text(
            'Say hello to Aariya',
            style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 16),
          ),
          const SizedBox(height: 6),
          Text(
            'Type a message or tap the mic to talk',
            style: TextStyle(color: Colors.white.withValues(alpha: 0.3), fontSize: 13),
          ),
        ],
      ),
    );
  }
}

/// "Aariya is thinking…" bubble while awaiting a reply.
class _ThinkingBubble extends StatelessWidget {
  const _ThinkingBubble();

  @override
  Widget build(BuildContext context) {
    return Align(
      alignment: Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        decoration: BoxDecoration(
          color: Colors.blueGrey.withValues(alpha: 0.3),
          borderRadius: BorderRadius.circular(20),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            SizedBox(
              width: 12,
              height: 12,
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: Colors.cyanAccent.withValues(alpha: 0.8),
              ),
            ),
            const SizedBox(width: 10),
            Text(
              'thinking…',
              style: TextStyle(color: Colors.white.withValues(alpha: 0.5), fontSize: 14),
            ),
          ],
        ),
      ),
    );
  }
}

import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_tts/flutter_tts.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/article.dart';
import '../services/news_service.dart';

enum TtsState { stopped, playing, paused }

class ArticleScreen extends StatefulWidget {
  final Article article;

  const ArticleScreen({super.key, required this.article});

  @override
  State<ArticleScreen> createState() => _ArticleScreenState();
}

class _ArticleScreenState extends State<ArticleScreen> {
  final FlutterTts _tts = FlutterTts();
  final ScrollController _scrollController = ScrollController();
  TtsState _ttsState = TtsState.stopped;
  double _progress = 0.0;
  bool _autoScroll = false;
  List<String> _words = [];
  Timer? _progressTimer;
  double _rate = 0.45;
  final double _pitch = 1.0;
  bool _bookmarked = false;
  final NewsService _service = NewsService();

  @override
  void initState() {
    super.initState();
    _initTts();
    _words = _readingText.split(RegExp(r'\s+'));
  }

  @override
  void dispose() {
    _tts.stop();
    _scrollController.dispose();
    _progressTimer?.cancel();
    super.dispose();
  }

  Future<void> _initTts() async {
    await _tts.setLanguage('en-US');
    await _tts.setSpeechRate(_rate);
    await _tts.setPitch(_pitch);
    _tts.setCompletionHandler(() {
      setState(() {
        _ttsState = TtsState.stopped;
        _autoScroll = false;
        _progress = 1.0;
      });
      _progressTimer?.cancel();
    });
    _tts.setProgressHandler((String text, int start, int end, String word) {
      if (_autoScroll) {
        final total = _words.length;
        setState(() {
          _progress = total > 0 ? (start / total) : 0.0;
        });
      }
    });
  }

  String get _readingText {
    final buf = StringBuffer();
    buf.writeln(widget.article.title);
    if (widget.article.summary != null) {
      buf.writeln(widget.article.summary);
    }
    if (widget.article.description != null) {
      buf.writeln(widget.article.description);
    }
    return buf.toString();
  }

  Future<void> _play() async {
    await _tts.stop();
    setState(() {
      _progress = 0.0;
      _autoScroll = true;
    });
    await _tts.speak(_readingText);
    setState(() => _ttsState = TtsState.playing);
    _startAutoScroll();
  }

  void _startAutoScroll() {
    _progressTimer?.cancel();
    _progressTimer = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (!_autoScroll || !_scrollController.hasClients) return;
      final maxScroll = _scrollController.position.maxScrollExtent;
      final currentScroll = _scrollController.offset;
      final step = maxScroll * 0.003;
      if (currentScroll < maxScroll) {
        _scrollController.animateTo(
          math.min(currentScroll + step, maxScroll),
          duration: const Duration(milliseconds: 150),
          curve: Curves.linear,
        );
      }
    });
  }

  Future<void> _pause() async {
    await _tts.pause();
    setState(() {
      _ttsState = TtsState.paused;
      _autoScroll = false;
    });
    _progressTimer?.cancel();
  }

  Future<void> _resume() async {
    await _tts.speak(_readingText);
    setState(() {
      _ttsState = TtsState.playing;
      _autoScroll = true;
    });
    _startAutoScroll();
  }

  Future<void> _stop() async {
    await _tts.stop();
    setState(() {
      _ttsState = TtsState.stopped;
      _autoScroll = false;
      _progress = 0.0;
    });
    _progressTimer?.cancel();
  }

  void _share(Article article) {
    Clipboard.setData(ClipboardData(text: '${article.title}\n${article.url}'));
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Link copied to clipboard'), duration: Duration(seconds: 2)),
    );
  }

  Future<void> _showSpeedDialog() async {
    final result = await showDialog<double>(
      context: context,
      builder: (ctx) => SimpleDialog(
        title: const Text('Reading Speed'),
        children: [
          RadioGroup<double>(
            groupValue: _rate,
            onChanged: (v) => Navigator.pop(ctx, v),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [0.25, 0.35, 0.45, 0.55, 0.65].map((r) {
                return RadioListTile<double>(
                  title: Text('${(r * 100).round()}%'),
                  value: r,
                );
              }).toList(),
            ),
          ),
        ],
      ),
    );
    if (result != null) {
      setState(() => _rate = result);
      await _tts.setSpeechRate(_rate);
    }
  }

  @override
  Widget build(BuildContext context) {
    final article = widget.article;
    final showProgress = _ttsState == TtsState.playing && _autoScroll;
    return Scaffold(
      appBar: AppBar(
        title: Text(
          article.category?.toUpperCase() ?? 'ARTICLE',
          style: const TextStyle(fontSize: 14),
        ),
        actions: [
          if (_ttsState == TtsState.playing || _ttsState == TtsState.paused)
            IconButton(
              icon: const Icon(Icons.speed),
              onPressed: _showSpeedDialog,
              tooltip: 'Reading speed',
            ),
          IconButton(
            icon: Icon(_bookmarked ? Icons.bookmark : Icons.bookmark_border),
            onPressed: () {
              setState(() => _bookmarked = !_bookmarked);
              _service.sendFeedback(article.id, 'save');
            },
            tooltip: 'Save',
          ),
          IconButton(
            icon: const Icon(Icons.share),
            onPressed: () => _share(article),
            tooltip: 'Share',
          ),
          if (article.url.isNotEmpty)
            IconButton(
              icon: const Icon(Icons.open_in_browser),
              onPressed: () async {
                final uri = Uri.tryParse(article.url);
                if (uri != null && await canLaunchUrl(uri)) {
                  await launchUrl(uri, mode: LaunchMode.externalApplication);
                }
              },
              tooltip: 'Open in browser',
            ),
        ],
      ),
      body: Column(
        children: [
          if (showProgress)
            LinearProgressIndicator(
              value: _progress.clamp(0.0, 1.0),
              backgroundColor: Colors.grey[800],
            ),
          Expanded(
            child: SingleChildScrollView(
              controller: _scrollController,
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    article.title,
                    style: const TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      if (article.author != null) ...[
                        Text(
                          article.author!,
                          style: TextStyle(color: Colors.grey[400], fontSize: 13),
                        ),
                        const SizedBox(width: 12),
                      ],
                      if (article.publishedAt != null)
                        Text(
                          article.publishedAt!,
                          style: TextStyle(color: Colors.grey[600], fontSize: 13),
                        ),
                    ],
                  ),
                  if (article.summary != null) ...[
                    const SizedBox(height: 16),
                    Container(
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                        color: Colors.blueGrey.withAlpha(30),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.blueGrey.withAlpha(60)),
                      ),
                      child: Text(
                        article.summary!,
                        style: const TextStyle(
                          fontSize: 15,
                          fontStyle: FontStyle.italic,
                          height: 1.4,
                        ),
                      ),
                    ),
                  ],
                  if (article.description != null) ...[
                    const SizedBox(height: 16),
                    Text(
                      article.description!,
                      style: const TextStyle(fontSize: 15, height: 1.5),
                    ),
                  ],
                  if (article.keyEntities != null && article.keyEntities!.isNotEmpty) ...[
                    const SizedBox(height: 16),
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: article.keyEntities!.map((e) {
                        return Chip(
                          label: Text(e, style: const TextStyle(fontSize: 12)),
                          materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                        );
                      }).toList(),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (_ttsState == TtsState.playing && _autoScroll)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    'Auto-scrolling with TTS...',
                    style: TextStyle(fontSize: 11, color: Colors.grey[500]),
                  ),
                ),
              Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  if (_ttsState == TtsState.stopped)
                    _controlButton(Icons.play_arrow, 'Listen', _play),
                  if (_ttsState == TtsState.playing) ...[
                    _controlButton(Icons.pause, 'Pause', _pause),
                    const SizedBox(width: 16),
                    _controlButton(Icons.stop, 'Stop', _stop),
                  ],
                  if (_ttsState == TtsState.paused) ...[
                    _controlButton(Icons.play_arrow, 'Resume', _resume),
                    const SizedBox(width: 16),
                    _controlButton(Icons.stop, 'Stop', _stop),
                  ],
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _controlButton(IconData icon, String label, VoidCallback onPressed) {
    return ElevatedButton.icon(
      onPressed: onPressed,
      icon: Icon(icon, size: 20),
      label: Text(label),
      style: ElevatedButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      ),
    );
  }
}

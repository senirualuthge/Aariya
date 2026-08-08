import 'dart:async';

import 'package:flutter/material.dart';

import '../models/article.dart';
import '../services/news_service.dart';
import '../services/voice_service.dart';
import '../widgets/article_card.dart';
import 'article_screen.dart';
import 'chat_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final NewsService _service = NewsService();
  final VoiceService _voice = VoiceService();
  List<Article> _articles = [];
  Set<String> _categories = {};
  String? _selectedCategory;
  bool _loading = true;
  bool _voiceEnabled = false;
  String? _error;
  StreamSubscription? _feedSub;
  StreamSubscription? _updateSub;
  StreamSubscription? _voiceSub;

  @override
  void initState() {
    super.initState();
    _init();
  }

  Future<void> _init() async {
    _feedSub = _service.feedStream.listen((articles) {
      if (mounted) {
        setState(() {
          _articles = articles;
          _categories = articles
              .map((a) => a.category ?? 'other')
              .where((c) => c.isNotEmpty)
              .toSet();
        });
      }
    });

    _updateSub = _service.updateStream.listen((article) {
      if (article.isRisk == true && (article.importance ?? 0) >= 7) {
        _showBreakingAlert(article);
      }
    });

    // Connect WebSocket before fetch so no updates are missed
    _service.connectWebSocket();

    try {
      await _service.fetchNews();
    } catch (e) {
      if (mounted) setState(() => _error = e.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }

    // Voice commands
    await _voice.initialize();
    if (_voice.isAvailable && mounted) {
      setState(() => _voiceEnabled = true);
      _voice.startListening();
      _voiceSub = _voice.commandStream?.listen(_handleVoiceCommand);
    }
  }

  void _handleVoiceCommand(VoiceCommand cmd) {
    if (!mounted) return;
    switch (cmd) {
      case VoiceCommand.readHeadlines:
        _showHeadlines();
      case VoiceCommand.readTopStory:
        _openArticle(0);
      case VoiceCommand.readTechNews:
        setState(() => _selectedCategory = 'tech');
      case VoiceCommand.readEconomyNews:
        setState(() => _selectedCategory = 'economy');
      case VoiceCommand.readGlobalNews:
        setState(() => _selectedCategory = 'global');
      case VoiceCommand.readSecurityNews:
        setState(() => _selectedCategory = 'security');
      case VoiceCommand.stop:
        _voice.stopListening();
      case VoiceCommand.nextArticle:
        _openArticle(1);
      case VoiceCommand.askQuestion:
        _openChat();
      case VoiceCommand.unknown:
        break;
    }
  }

  void _openChat() {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => const ChatScreen(),
      ),
    );
  }

  void _showHeadlines() {
    final count = _filteredArticles.length;
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('$count headlines available')),
      );
    }
  }

  void _openArticle(int index) {
    final filtered = _filteredArticles;
    if (index < filtered.length) {
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => ArticleScreen(article: filtered[index]),
        ),
      );
    }
  }

  void _showBreakingAlert(Article article) {
    if (!mounted) return;
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Row(
          children: [
            const Icon(Icons.warning_amber, color: Colors.red, size: 28),
            const SizedBox(width: 8),
            const Text('BREAKING'),
          ],
        ),
        content: Text(article.title, style: const TextStyle(fontSize: 16)),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Dismiss'),
          ),
          FilledButton(
            onPressed: () {
              Navigator.pop(ctx);
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => ArticleScreen(article: article),
                ),
              );
            },
            child: const Text('Read Now'),
          ),
        ],
      ),
    );
  }

  List<Article> get _filteredArticles {
    var list = _articles;
    if (_selectedCategory != null) {
      list = list.where((a) => a.category == _selectedCategory).toList();
    }
    list.sort((a, b) {
      final aScore = a.rankScore ?? 0;
      final bScore = b.rankScore ?? 0;
      return bScore.compareTo(aScore);
    });
    return list;
  }

  @override
  void dispose() {
    _feedSub?.cancel();
    _updateSub?.cancel();
    _voiceSub?.cancel();
    _service.dispose();
    _voice.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pulse AI News'),
        centerTitle: false,
        actions: [
          if (_voiceEnabled)
            IconButton(
              icon: Icon(
                _voice.isListening ? Icons.mic : Icons.mic_none,
                color: _voice.isListening ? Colors.blue : null,
              ),
              onPressed: () {
                if (_voice.isListening) {
                  _voice.stopListening();
                } else {
                  _voice.startListening();
                }
                setState(() {});
              },
              tooltip: 'Voice commands',
            ),
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: () async {
              setState(() => _loading = true);
              await _service.fetchNews();
              setState(() => _loading = false);
            },
          ),
        ],
      ),
      body: Column(
        children: [
          if (_voiceEnabled && _voice.isListening)
            Container(
              padding: const EdgeInsets.symmetric(vertical: 4),
              color: Colors.blue.withAlpha(20),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  const Icon(Icons.hearing, size: 16, color: Colors.blue),
                  const SizedBox(width: 6),
                  Text(
                    'Listening... "Read headlines", "Top story", "Tech news"',
                    style: TextStyle(fontSize: 12, color: Colors.blue[300]),
                  ),
                ],
              ),
            ),
          if (_categories.isNotEmpty)
            SizedBox(
              height: 44,
              child: ListView(
                scrollDirection: Axis.horizontal,
                padding: const EdgeInsets.symmetric(horizontal: 8),
                children: [
                  _filterChip('All', null),
                  ..._categories.map((c) => _filterChip(
                        c[0].toUpperCase() + c.substring(1),
                        c,
                      )),
                ],
              ),
            ),
          Expanded(
            child: _buildBody(),
          ),
        ],
      ),
    );
  }

  Widget _filterChip(String label, String? category) {
    final selected = _selectedCategory == category;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
      child: FilterChip(
        label: Text(label),
        selected: selected,
        onSelected: (_) => setState(() => _selectedCategory = category),
        materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
      ),
    );
  }

  Widget _buildBody() {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_error != null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.cloud_off, size: 48, color: Colors.grey[600]),
            const SizedBox(height: 8),
            Text('Could not load news', style: TextStyle(color: Colors.grey[400])),
            const SizedBox(height: 8),
            TextButton(
              onPressed: () async {
                setState(() => _error = null);
                try {
                  await _service.fetchNews();
                } catch (e) {
                  setState(() => _error = e.toString());
                }
              },
              child: const Text('Retry'),
            ),
          ],
        ),
      );
    }

    final filtered = _filteredArticles;
    if (filtered.isEmpty) {
      return Center(
        child: Text(
          _selectedCategory != null
              ? 'No $_selectedCategory news yet'
              : 'No news yet. Waiting for next fetch cycle...',
          style: TextStyle(color: Colors.grey[400]),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => _service.fetchNews(),
      child: ListView.builder(
        padding: const EdgeInsets.only(top: 4, bottom: 80),
        itemCount: filtered.length,
        itemBuilder: (ctx, i) {
          final article = filtered[i];
          return ArticleCard(
            article: article,
            onTap: () {
              _service.sendFeedback(article.id, 'click');
              Navigator.push(
                context,
                MaterialPageRoute(
                  builder: (_) => ArticleScreen(article: article),
                ),
              );
            },
          );
        },
      ),
    );
  }
}

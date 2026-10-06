import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:http/http.dart' as http;
import 'package:web_socket_channel/web_socket_channel.dart';

import '../models/article.dart';
import 'api_config.dart';
import 'session.dart';

class NewsService {
  static final String _baseUrl = ApiConfig.baseUrl;
  static final String _wsUrl = ApiConfig.wsUrl;

  final List<Article> _articles = [];
  WebSocketChannel? _channel;
  StreamSubscription? _subscription;

  int _reconnectAttempt = 0;
  static const int _maxReconnectDelay = 30;
  Timer? _reconnectTimer;

  final StreamController<List<Article>> _feedController =
      StreamController<List<Article>>.broadcast();
  final StreamController<Article> _updateController =
      StreamController<Article>.broadcast();

  Stream<List<Article>> get feedStream => _feedController.stream;
  Stream<Article> get updateStream => _updateController.stream;
  List<Article> get articles => List.unmodifiable(_articles);

  Future<void> fetchNews({
    int limit = 20,
    int minImportance = 4,
    String? category,
  }) async {
    final params = <String, String>{
      'limit': limit.toString(),
      'min_importance': minImportance.toString(),
    };
    if (category != null) params['category'] = category;

    final uri = Uri.parse('$_baseUrl/api/news').replace(queryParameters: params);
    try {
      final resp = await http.get(uri);
      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body) as Map<String, dynamic>;
        final rawList = data['data'] as List<dynamic>;
        _articles.clear();
        for (final item in rawList) {
          _articles.add(Article.fromJson(item as Map<String, dynamic>));
        }
        _feedController.add(List.from(_articles));
      }
    } catch (e) {
      throw Exception('Failed to fetch news: $e');
    }
  }

  void connectWebSocket() {
    _reconnectAttempt = 0;
    _doConnect();
  }

  void _doConnect() {
    _channel?.sink.close();
    _subscription?.cancel();
    try {
      _channel = WebSocketChannel.connect(Uri.parse(_wsUrl));
      // web_socket_channel 3.x also completes the channel's `ready`
      // future with a connect failure. The stream's onError below
      // already logs/retries it, so observe `ready` and drop the
      // duplicate — otherwise Dart reports an "Unhandled Exception"
      // on every offline reconnect attempt.
      _channel!.ready.catchError((_) {
        // Stream onError already scheduled a reconnect.
      });
      _subscription = _channel!.stream.listen(
        (raw) {
          _reconnectAttempt = 0;
          try {
            final msg = jsonDecode(raw as String) as Map<String, dynamic>;
            if (msg['type'] == 'news_update') {
              final article = Article.fromJson(msg);
              _articles.insert(0, article);
              _feedController.add(List.from(_articles));
              _updateController.add(article);
            }
          } catch (_) {}
        },
        onError: (_) => _scheduleReconnect(),
        onDone: () => _scheduleReconnect(),
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _scheduleReconnect() {
    _reconnectTimer?.cancel();
    final delay = min(
      _maxReconnectDelay,
      2 + pow(2, _reconnectAttempt).toInt(),
    );
    _reconnectAttempt++;
    _reconnectTimer = Timer(Duration(seconds: delay), _doConnect);
  }

  Future<void> sendFeedback(String articleId, String type) async {
    final uri = Uri.parse('$_baseUrl/api/feedback/$articleId')
        .replace(queryParameters: {'type': type, 'user_id': Session.instance.userId});
    try {
      await http.post(uri);
    } catch (_) {}
  }

  void dispose() {
    _reconnectTimer?.cancel();
    _subscription?.cancel();
    _channel?.sink.close();
    _feedController.close();
    _updateController.close();
  }
}

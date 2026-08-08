class Article {
  final String id;
  final String title;
  final String url;
  final String? summary;
  final String? description;
  final String? category;
  final int? importance;
  final bool? isRisk;
  final List<String>? keyEntities;
  final String? author;
  final String? sourceId;
  final String? publishedAt;
  final double? rankScore;

  Article({
    required this.id,
    required this.title,
    required this.url,
    this.summary,
    this.description,
    this.category,
    this.importance,
    this.isRisk,
    this.keyEntities,
    this.author,
    this.sourceId,
    this.publishedAt,
    this.rankScore,
  });

  factory Article.fromJson(Map<String, dynamic> json) {
    return Article(
      id: json['id'] as String? ?? '',
      title: json['title'] as String? ?? '',
      url: json['url'] as String? ?? '',
      summary: json['summary'] as String?,
      description: json['description'] as String?,
      category: json['category'] as String?,
      importance: json['importance'] as int?,
      isRisk: json['is_risk'] as bool?,
      keyEntities: (json['key_entities'] as List<dynamic>?)
          ?.map((e) => e.toString())
          .toList(),
      author: json['author'] as String?,
      sourceId: json['source_id'] as String?,
      publishedAt: json['published_at'] as String?,
      rankScore: (json['rank_score'] as num?)?.toDouble(),
    );
  }

  String get displayImportance {
    if (importance == null) return '';
    if (importance! >= 9) return 'CRITICAL';
    if (importance! >= 7) return 'BREAKING';
    if (importance! >= 5) return 'HIGH';
    if (importance! >= 3) return 'MEDIUM';
    return 'LOW';
  }
}

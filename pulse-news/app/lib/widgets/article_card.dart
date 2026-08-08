import 'package:flutter/material.dart';

import '../models/article.dart';

class ArticleCard extends StatelessWidget {
  final Article article;
  final VoidCallback onTap;

  const ArticleCard({super.key, required this.article, required this.onTap});

  Color _urgencyColor() {
    final imp = article.importance ?? 0;
    if (imp >= 9) return Colors.redAccent;
    if (imp >= 7) return Colors.orangeAccent;
    if (imp >= 5) return Colors.amber;
    return Colors.grey;
  }

  IconData _categoryIcon() {
    switch (article.category) {
      case 'tech':
        return Icons.computer;
      case 'economy':
        return Icons.trending_up;
      case 'global':
        return Icons.public;
      case 'security':
        return Icons.shield;
      default:
        return Icons.article;
    }
  }

  @override
  Widget build(BuildContext context) {
    final urgencyColor = _urgencyColor();
    return Card(
      margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Padding(
          padding: const EdgeInsets.all(14),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(_categoryIcon(), color: urgencyColor, size: 28),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      article.title,
                      style: const TextStyle(
                        fontWeight: FontWeight.w600,
                        fontSize: 15,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    if (article.summary != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        article.summary!,
                        style: TextStyle(
                          color: Colors.grey[400],
                          fontSize: 13,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                    const SizedBox(height: 6),
                    Row(
                      children: [
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 2,
                          ),
                          decoration: BoxDecoration(
                            color: urgencyColor.withAlpha(40),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            article.displayImportance,
                            style: TextStyle(
                              color: urgencyColor,
                              fontSize: 11,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                        if (article.isRisk == true) ...[
                          const SizedBox(width: 6),
                          const Icon(Icons.warning_amber, size: 16, color: Colors.red),
                        ],
                        const Spacer(),
                        if (article.rankScore != null)
                          Text(
                            article.rankScore!.toStringAsFixed(2),
                            style: TextStyle(
                              color: Colors.grey[600],
                              fontSize: 11,
                            ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

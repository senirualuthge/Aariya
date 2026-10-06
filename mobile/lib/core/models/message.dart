class Message {
  final String id;
  final String text;
  final bool isUser;
  final int timestamp;
  final String? emotion;

  Message({
    required this.id,
    required this.text,
    required this.isUser,
    required this.timestamp,
    this.emotion,
  });

  factory Message.fromJson(Map<String, dynamic> json, {bool isUser = false}) {
    return Message(
      id: json['id'] ?? DateTime.now().millisecondsSinceEpoch.toString(),
      text: json['text'] ?? '',
      isUser: isUser,
      timestamp: json['timestamp'] ?? DateTime.now().millisecondsSinceEpoch,
      emotion: json['emotion'],
    );
  }

  Message copyWith({
    String? id,
    String? text,
    bool? isUser,
    int? timestamp,
    String? emotion,
  }) {
    return Message(
      id: id ?? this.id,
      text: text ?? this.text,
      isUser: isUser ?? this.isUser,
      timestamp: timestamp ?? this.timestamp,
      emotion: emotion ?? this.emotion,
    );
  }
}

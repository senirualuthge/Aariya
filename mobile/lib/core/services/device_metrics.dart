import 'dart:async';
import 'dart:io';

import 'package:battery_plus/battery_plus.dart';
import 'package:device_info_plus/device_info_plus.dart';
import 'package:flutter/foundation.dart';

import 'websocket_service.dart';

/// Collects the phone's own device metrics and reports them to the backend.
///
/// Every [_interval] the reporter gathers:
///   * **battery** — level (0–100, `battery_plus`) + charging state
///   * **cpu_percent** — live CPU usage. Android only: parsed from `/proc/stat`
///     (delta between samples), no native code. iOS returns `null` (the OS
///     doesn't expose per-process CPU through public APIs without a native
///     channel), so the dashboard shows "—" there.
///   * **memory** — used/total + percent. Android only: `/proc/meminfo`
///     (`MemTotal` / `MemAvailable`). iOS returns `null`.
///   * **device** — platform, model, OS version via `device_info_plus`
///
/// The payload is pushed as a `device_metrics` frame on the control channel
/// (`/ws/mobile/control`). The server stores it on the mobile gateway agent,
/// and the Analytics Dashboard's System Health → Mobile App panel renders it.
///
/// Fire-and-forget by design: telemetry must NOT go through the reliable
/// outbox (a flaky link would spam retries for a metric that is stale the
/// moment it's sent).
///
/// Testability: both the collector and the send function are injectable, so a
/// widget/unit test can drive a fake collector and capture the frame shape
/// with `fake_async` — no platform channels, no sockets.
class DeviceMetricsReporter {
  DeviceMetricsReporter({
    Duration interval = const Duration(seconds: 10),
    FutureOr<Map<String, dynamic>> Function()? collector,
    void Function(Map<String, dynamic> frame)? send,
  }) : _interval = interval {
    // Assigned in the body — an instance method can't be referenced in a
    // field-initializer list (implicit `this` is not yet available there).
    _collector = collector ?? _collectDeviceMetrics;
    _send = send ?? _sendFrame;
  }

  /// Shared app-wide reporter (started from [bootstrap]).
  static final DeviceMetricsReporter instance = DeviceMetricsReporter();

  /// How often device metrics are pushed.
  final Duration _interval;

  /// Injectable metric collector (defaults to the real platform collector).
  late final FutureOr<Map<String, dynamic>> Function() _collector;

  /// Injectable frame sink (defaults to the WebSocket control channel).
  late final void Function(Map<String, dynamic> frame) _send;

  Timer? _timer;
  bool _started = false;

  /// Starts periodic reporting. Idempotent.
  void start() {
    if (_started) return;
    _started = true;
    _timer = Timer.periodic(_interval, (_) => _tick());
    // One immediate sample so the dashboard isn't empty for the first interval.
    _tick();
  }

  /// Stops periodic reporting. Safe to call when not started.
  void stop() {
    _started = false;
    _timer?.cancel();
    _timer = null;
  }

  Future<void> _tick() async {
    try {
      final device = await _collector();
      if (device.isEmpty) return;
      _send({
        'type': 'device_metrics',
        'device': device,
        'ts': DateTime.now().millisecondsSinceEpoch / 1000,
      });
    } catch (e) {
      debugPrint('[DeviceMetrics] collect failed: $e');
    }
  }

  // ── Default frame sink ─────────────────────────────────────────────────────

  static void _sendFrame(Map<String, dynamic> frame) {
    // Pass the frame's timestamp through so the wire frame carries the same
    // ts that was computed in _tick (no second DateTime.now() on the wire).
    WebSocketService.instance.sendDeviceMetrics(
      frame['device'] as Map<String, dynamic>,
      ts: frame['ts'] as num?,
    );
  }

  // ── Default collector (real platform metrics) ──────────────────────────────

  final Battery _battery = Battery();
  final DeviceInfoPlugin _deviceInfo = DeviceInfoPlugin();
  Map<String, dynamic>? _deviceInfoCache;

  // Previous /proc/stat sample for CPU% delta computation (Android).
  int? _prevCpuTotal;
  int? _prevCpuIdle;

  Future<Map<String, dynamic>> _collectDeviceMetrics() async {
    final metrics = <String, dynamic>{
      'platform': Platform.operatingSystem, // 'android' | 'ios' | ...
      'ts': DateTime.now().millisecondsSinceEpoch / 1000,
    };

    // ── Battery (both platforms, via battery_plus) ─────────────────────────
    try {
      final level = await _battery.batteryLevel; // 0..100 int
      metrics['battery'] = level.clamp(0, 100);
      try {
        final state = await _battery.batteryState;
        metrics['charging'] =
            state == BatteryState.charging || state == BatteryState.full;
      } catch (_) {
        metrics['charging'] = false;
      }
    } catch (_) {
      // Battery API unavailable (e.g. unsupported platform) — omit.
    }

    // ── Device info (cached — it never changes at runtime) ─────────────────
    if (_deviceInfoCache == null) {
      try {
        _deviceInfoCache = await _loadDeviceInfo();
      } catch (e) {
        debugPrint('[DeviceMetrics] device info unavailable: $e');
        _deviceInfoCache = <String, dynamic>{};
      }
    }
    metrics.addAll(_deviceInfoCache!);

    // ── CPU + memory (Android via /proc; iOS reports null) ─────────────────
    if (Platform.isAndroid) {
      final cpu = _readCpuPercent();
      if (cpu != null) metrics['cpu_percent'] = cpu;
      final mem = _readMemory();
      if (mem != null) metrics.addAll(mem);
    }

    return metrics;
  }

  Future<Map<String, dynamic>> _loadDeviceInfo() async {
    if (Platform.isAndroid) {
      final info = await _deviceInfo.androidInfo;
      return {
        'model': info.model,
        'manufacturer': info.manufacturer,
        'os_version': 'Android ${info.version.release}',
      };
    }
    if (Platform.isIOS) {
      final info = await _deviceInfo.iosInfo;
      return {
        'model': info.utsname.machine.isNotEmpty ? info.utsname.machine : info.model,
        'manufacturer': 'Apple',
        'os_version': '${info.systemName} ${info.systemVersion}',
      };
    }
    return <String, dynamic>{};
  }

  /// CPU usage % from two `/proc/stat` samples (delta). `null` on first call
  /// or when `/proc` is unreadable (Android-only code path).
  double? _readCpuPercent() {
    try {
      final file = File('/proc/stat').readAsStringSync();
      final line = file.split('\n').firstWhere(
            (l) => l.startsWith('cpu '),
            orElse: () => '',
          );
      if (line.isEmpty) return null;
      final parts = line.split(RegExp(r'\s+')).skip(1).take(8).map(int.tryParse).whereType<int>().toList();
      if (parts.length < 4) return null;

      // Standard Linux CPU ticks: user nice system idle iowait irq softirq steal
      final idle = parts[3] + (parts.length > 4 ? parts[4] : 0);
      final total = parts.fold<int>(0, (sum, v) => sum + v);

      if (_prevCpuTotal != null && _prevCpuIdle != null) {
        final dTotal = total - _prevCpuTotal!;
        final dIdle = idle - _prevCpuIdle!;
        if (dTotal > 0) {
          final percent = (1 - dIdle / dTotal) * 100;
          _prevCpuTotal = total;
          _prevCpuIdle = idle;
          return double.parse(percent.toStringAsFixed(1));
        }
      }
      _prevCpuTotal = total;
      _prevCpuIdle = idle;
      return null; // first sample — need a baseline
    } catch (_) {
      return null;
    }
  }

  /// Memory from `/proc/meminfo` (Android-only code path): percent + GB.
  Map<String, dynamic>? _readMemory() {
    try {
      final lines = File('/proc/meminfo').readAsLinesSync();
      int memTotalKb = 0;
      int memAvailKb = 0;
      for (final line in lines) {
        final fields = line.split(RegExp(r'\s+'));
        if (fields.length < 2) continue;
        if (line.startsWith('MemTotal:')) {
          memTotalKb = int.tryParse(fields[1]) ?? 0;
        } else if (line.startsWith('MemAvailable:')) {
          memAvailKb = int.tryParse(fields[1]) ?? 0;
        }
      }
      if (memTotalKb <= 0) return null;
      final usedKb = memAvailKb > 0 ? memTotalKb - memAvailKb : memTotalKb;
      final totalGb = memTotalKb / (1024 * 1024);
      final usedGb = usedKb / (1024 * 1024);
      return {
        'ram_percent': double.parse(((usedKb / memTotalKb) * 100).toStringAsFixed(1)),
        'ram_used_gb': double.parse(usedGb.toStringAsFixed(2)),
        'ram_total_gb': double.parse(totalGb.toStringAsFixed(2)),
      };
    } catch (_) {
      return null;
    }
  }
}

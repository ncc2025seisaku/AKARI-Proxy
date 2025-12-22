import 'dart:async';
import 'package:flutter/foundation.dart';

/// Represents a single log entry for a proxy request.
class ProxyLogEntry {
  final DateTime timestamp;
  final String method;
  final String url;
  final int statusCode;
  final int bytesSent;
  final int bytesReceived;
  final String? error;

  ProxyLogEntry({
    required this.timestamp,
    required this.method,
    required this.url,
    required this.statusCode,
    this.bytesSent = 0,
    this.bytesReceived = 0,
    this.error,
  });
}

/// Service to monitor proxy activity.
class MonitoringService extends ChangeNotifier {
  static final MonitoringService _instance = MonitoringService._internal();
  factory MonitoringService() => _instance;
  MonitoringService._internal();

  final List<ProxyLogEntry> _logs = [];
  final _logController = StreamController<ProxyLogEntry>.broadcast();

  List<ProxyLogEntry> get logs => List.unmodifiable(_logs);
  Stream<ProxyLogEntry> get logStream => _logController.stream;

  // Stats
  int _totalBytesSent = 0;
  int _totalBytesReceived = 0;
  int _totalRequests = 0;
  int _errorRequests = 0;
  int get totalBytesSent => _totalBytesSent;
  int get totalBytesReceived => _totalBytesReceived;
  int get totalRequests => _totalRequests;
  int get errorRequests => _errorRequests;
  int get successRequests => _totalRequests - _errorRequests;

  Timer? _throttleTimer;

  void addLog(ProxyLogEntry entry) {
    _logs.insert(0, entry);
    if (_logs.length > 500) {
      _logs.removeLast();
    }

    _totalBytesSent += entry.bytesSent;
    _totalBytesReceived += entry.bytesReceived;
    _totalRequests++;
    if (entry.statusCode >= 400 || entry.error != null) {
      _errorRequests++;
    }

    _logController.add(entry);

    // Throttle UI updates to at most 10Hz to prevent main thread blocking
    if (_throttleTimer == null || !_throttleTimer!.isActive) {
      _throttleTimer = Timer(const Duration(milliseconds: 100), () {
        notifyListeners();
      });
    }
  }

  void clearLogs() {
    _logs.clear();
    notifyListeners();
  }

  @override
  void dispose() {
    _throttleTimer?.cancel();
    _logController.close();
    super.dispose();
  }
}

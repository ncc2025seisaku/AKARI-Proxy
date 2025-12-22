import 'package:flutter/material.dart';
import '../services/monitoring_service.dart';
import 'package:intl/intl.dart';

class MonitoringView extends StatelessWidget {
  const MonitoringView({super.key});

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: MonitoringService(),
      builder: (context, _) {
        final service = MonitoringService();
        final logs = service.logs;

        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Dashboard Stats
            _buildDashboard(service),

            const Divider(height: 1, color: Colors.white10),

            // Logs Header
            Padding(
              padding: const EdgeInsets.all(16.0),
              child: Row(
                children: [
                  const Icon(
                    Icons.list_alt,
                    color: Color(0xFFF3C45C),
                    size: 18,
                  ),
                  const SizedBox(width: 8),
                  const Text(
                    '接続ログ',
                    style: TextStyle(
                      color: Colors.white,
                      fontSize: 16,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const Spacer(),
                  TextButton.icon(
                    onPressed: () => service.clearLogs(),
                    icon: const Icon(Icons.delete_outline, size: 16),
                    label: const Text('クリア'),
                    style: TextButton.styleFrom(
                      foregroundColor: Colors.white54,
                    ),
                  ),
                ],
              ),
            ),

            // Logs List
            Expanded(
              child: logs.isEmpty
                  ? const Center(
                      child: Text(
                        'ログはありません',
                        style: TextStyle(color: Colors.white30),
                      ),
                    )
                  : ListView.separated(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      itemCount: logs.length,
                      separatorBuilder: (context, index) =>
                          const Divider(height: 1, color: Colors.white10),
                      itemBuilder: (context, index) {
                        return _buildLogTile(logs[index]);
                      },
                    ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildDashboard(MonitoringService service) {
    final successRate = service.totalRequests > 0
        ? (service.successRequests / service.totalRequests * 100)
              .toStringAsFixed(1)
        : '0.0';

    return Container(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Requests stats row
          Row(
            children: [
              _buildStatItem(
                label: 'リクエスト',
                value: service.totalRequests.toString(),
                icon: Icons.http,
                color: Colors.white70,
              ),
              const SizedBox(width: 16),
              _buildStatItem(
                label: '成功',
                value: service.successRequests.toString(),
                icon: Icons.check_circle_outline,
                color: Colors.greenAccent,
              ),
              const SizedBox(width: 16),
              _buildStatItem(
                label: 'エラー',
                value: service.errorRequests.toString(),
                icon: Icons.error_outline,
                color: Colors.redAccent,
              ),
            ],
          ),
          const SizedBox(height: 16),
          // Success rate bar
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(
                    '成功率',
                    style: TextStyle(
                      color: Colors.white.withOpacity(0.5),
                      fontSize: 11,
                    ),
                  ),
                  Text(
                    '$successRate%',
                    style: const TextStyle(
                      color: Colors.greenAccent,
                      fontSize: 11,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              ClipRRect(
                borderRadius: BorderRadius.circular(4),
                child: LinearProgressIndicator(
                  value: service.totalRequests > 0
                      ? service.successRequests / service.totalRequests
                      : 0.0,
                  backgroundColor: Colors.red.withOpacity(0.3),
                  valueColor: const AlwaysStoppedAnimation<Color>(
                    Colors.greenAccent,
                  ),
                  minHeight: 6,
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
          // Data usage section
          const Text(
            'データ使用量 (AKARI-UDP)',
            style: TextStyle(color: Colors.white70, fontSize: 13),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              _buildStatItem(
                label: '送信済み',
                value: _formatBytes(service.totalBytesSent),
                icon: Icons.upload,
                color: Colors.blueAccent,
              ),
              const SizedBox(width: 24),
              _buildStatItem(
                label: '受信済み',
                value: _formatBytes(service.totalBytesReceived),
                icon: Icons.download,
                color: Colors.greenAccent,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildStatItem({
    required String label,
    required String value,
    required IconData icon,
    required Color color,
  }) {
    return Expanded(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(icon, size: 14, color: color.withOpacity(0.7)),
              const SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  color: Colors.white.withOpacity(0.5),
                  fontSize: 11,
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            value,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 18,
              fontWeight: FontWeight.bold,
              letterSpacing: 0.5,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildLogTile(ProxyLogEntry entry) {
    final timeStr = DateFormat('HH:mm:ss').format(entry.timestamp);
    final isError = entry.statusCode >= 400 || entry.error != null;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Status Code Badge
          Container(
            width: 40,
            padding: const EdgeInsets.symmetric(vertical: 4),
            decoration: BoxDecoration(
              color: isError
                  ? Colors.red.withOpacity(0.2)
                  : Colors.green.withOpacity(0.2),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Center(
              child: Text(
                entry.statusCode.toString(),
                style: TextStyle(
                  color: isError ? Colors.redAccent : Colors.greenAccent,
                  fontSize: 12,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
          const SizedBox(width: 12),
          // Info
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Text(
                      entry.method,
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        entry.url,
                        style: const TextStyle(
                          color: Colors.white70,
                          fontSize: 12,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Text(
                      timeStr,
                      style: const TextStyle(
                        color: Colors.white30,
                        fontSize: 11,
                      ),
                    ),
                    const Spacer(),
                    if (entry.bytesReceived > 0)
                      Text(
                        '${_formatBytes(entry.bytesReceived)} received',
                        style: const TextStyle(
                          color: Colors.white30,
                          fontSize: 11,
                        ),
                      ),
                  ],
                ),
                if (entry.error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 4),
                    child: Text(
                      entry.error!,
                      style: const TextStyle(
                        color: Colors.redAccent,
                        fontSize: 11,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  String _formatBytes(int bytes) {
    if (bytes < 1024) return '$bytes B';
    if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
    if (bytes < 1024 * 1024 * 1024)
      return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
    return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
  }
}

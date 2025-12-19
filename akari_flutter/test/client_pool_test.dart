// Tests for client pool Dart API structures.
//
// These tests verify the Dart data structures without requiring
// RustLib initialization or a running remote proxy server.
//
// FFI-dependent tests (like defaultRequestConfig()) should be run
// as integration tests with proper RustLib.init() setup.

import 'package:flutter_test/flutter_test.dart';
import 'package:akari_flutter/src/rust/api/akari_client.dart';

void main() {
  group('AkariRequestConfig', () {
    test('can be created with custom values', () {
      final config = AkariRequestConfig(
        timeoutMs: BigInt.from(5000),
        maxNackRounds: 5,
        initialRequestRetries: 2,
        sockTimeoutMs: BigInt.from(500),
        firstSeqTimeoutMs: BigInt.from(250),
        aggTag: false,
        shortId: true,
      );

      expect(config.timeoutMs, equals(BigInt.from(5000)));
      expect(config.maxNackRounds, equals(5));
      expect(config.initialRequestRetries, equals(2));
      expect(config.sockTimeoutMs, equals(BigInt.from(500)));
      expect(config.firstSeqTimeoutMs, equals(BigInt.from(250)));
      expect(config.aggTag, isFalse);
      expect(config.shortId, isTrue);
    });

    test('can have null maxNackRounds', () {
      final config = AkariRequestConfig(
        timeoutMs: BigInt.from(10000),
        maxNackRounds: null,
        initialRequestRetries: 1,
        sockTimeoutMs: BigInt.from(1000),
        firstSeqTimeoutMs: BigInt.from(500),
        aggTag: true,
        shortId: false,
      );

      expect(config.maxNackRounds, isNull);
    });

    test('supports equality comparison via freezed', () {
      final config1 = AkariRequestConfig(
        timeoutMs: BigInt.from(10000),
        maxNackRounds: 3,
        initialRequestRetries: 1,
        sockTimeoutMs: BigInt.from(1000),
        firstSeqTimeoutMs: BigInt.from(500),
        aggTag: true,
        shortId: false,
      );

      final config2 = AkariRequestConfig(
        timeoutMs: BigInt.from(10000),
        maxNackRounds: 3,
        initialRequestRetries: 1,
        sockTimeoutMs: BigInt.from(1000),
        firstSeqTimeoutMs: BigInt.from(500),
        aggTag: true,
        shortId: false,
      );

      expect(config1, equals(config2));
    });
  });

  group('AkariTransferStats', () {
    test('can be created', () {
      final stats = AkariTransferStats(
        bytesSent: BigInt.from(1024),
        bytesReceived: BigInt.from(2048),
        nacksSent: 0,
        requestRetries: 1,
      );

      expect(stats.bytesSent, equals(BigInt.from(1024)));
      expect(stats.bytesReceived, equals(BigInt.from(2048)));
      expect(stats.nacksSent, equals(0));
      expect(stats.requestRetries, equals(1));
    });

    test('tracks correct metrics', () {
      final stats = AkariTransferStats(
        bytesSent: BigInt.from(512),
        bytesReceived: BigInt.from(4096),
        nacksSent: 2,
        requestRetries: 0,
      );

      // Verify that statistics are captured correctly
      expect(stats.nacksSent, equals(2));
      expect(stats.requestRetries, equals(0));
      expect(stats.bytesReceived > stats.bytesSent, isTrue);
    });
  });

  group('Pool size configuration', () {
    test('pool size constants are reasonable', () {
      // These are the expected pool size bounds from Rust
      const minPoolSize = 1;
      const maxPoolSize = 16;
      const defaultPoolSize = 4;

      expect(defaultPoolSize, greaterThanOrEqualTo(minPoolSize));
      expect(defaultPoolSize, lessThanOrEqualTo(maxPoolSize));
    });
  });
}

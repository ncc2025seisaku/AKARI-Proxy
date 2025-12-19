// Basic widget test for AKARI Proxy Flutter app

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:akari_flutter/main.dart';
import 'package:akari_flutter/src/services/settings_service.dart';

void main() {
  testWidgets('AKARI Proxy app smoke test', (WidgetTester tester) async {
    // Build our app with default settings and trigger a frame.
    final testSettings = AkariSettings(
      remoteHost: '127.0.0.1',
      remotePort: 9000,
      psk: [0, 1, 2, 3],
      useEncryption: false,
      enableJs: true,
      enableCss: true,
      enableImg: true,
      enableOther: true,
      useSystemProxy: false,
    );
    await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));

    // Verify that the app title is displayed.
    expect(find.text('AKARI Proxy'), findsOneWidget);

    // Verify that the status card is displayed.
    expect(find.text('Status'), findsOneWidget);

    // Verify that the URL input field exists.
    expect(find.byType(TextField), findsOneWidget);

    // Verify that the GO button exists.
    expect(find.text('GO'), findsOneWidget);
  });
}

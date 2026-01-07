import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:akari_flutter/main.dart';
import 'package:akari_flutter/src/rust/frb_generated.dart';
import 'package:akari_flutter/src/services/settings_service.dart';
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async => await RustLib.init());

  final testSettings = AkariSettings(
    remoteHost: '127.0.0.1',
    remotePort: 9000,
    psk: [0, 1, 2, 3],
    useEncryption: false,
    enableJs: true,
    enableCss: true,
    enableImg: true,
    enableOther: true,
  );

  group('Settings Panel Tests', () {
    testWidgets('Settings button opens settings panel', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      // Find and tap the settings button (gear icon)
      final settingsButton = find.byIcon(Icons.settings);
      expect(settingsButton, findsOneWidget);

      await tester.tap(settingsButton);
      await tester.pumpAndSettle();

      // Settings panel should now be visible with input fields
      expect(find.text('リモートホスト'), findsOneWidget);
      expect(find.text('ポート'), findsOneWidget);
    });

    testWidgets('Settings panel has encryption toggle', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      // Open settings
      await tester.tap(find.byIcon(Icons.settings));
      await tester.pumpAndSettle();

      // Check for encryption toggle
      expect(find.text('暗号化'), findsOneWidget);
    });

    testWidgets('Settings panel has filter toggles', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      // Open settings
      await tester.tap(find.byIcon(Icons.settings));
      await tester.pumpAndSettle();

      // Check for filter toggles
      expect(find.text('JavaScript'), findsOneWidget);
      expect(find.text('CSS'), findsOneWidget);
      expect(find.text('画像'), findsOneWidget);
    });

    testWidgets('Settings panel can be closed', (WidgetTester tester) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      // Open settings
      await tester.tap(find.byIcon(Icons.settings));
      await tester.pumpAndSettle();

      // Verify settings are open
      expect(find.text('リモートホスト'), findsOneWidget);

      // Close settings by tapping the button again
      await tester.tap(find.byIcon(Icons.settings));
      await tester.pumpAndSettle();

      // Settings should be closed (リモートホスト should not be visible)
      expect(find.text('リモートホスト'), findsNothing);
    });
  });
}

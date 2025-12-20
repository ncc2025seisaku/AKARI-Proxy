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
    useSystemProxy: false,
  );

  group('Navigation Tests', () {
    testWidgets('URL bar is present', (WidgetTester tester) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      // Find URL input field (TextFormField)
      final urlField = find.byType(TextFormField);
      expect(urlField, findsWidgets);
    });

    testWidgets('Navigation buttons are present', (WidgetTester tester) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      // Check for navigation icons
      expect(find.byIcon(Icons.arrow_back), findsOneWidget);
      expect(find.byIcon(Icons.arrow_forward), findsOneWidget);
      expect(find.byIcon(Icons.refresh), findsOneWidget);
      expect(find.byIcon(Icons.home), findsOneWidget);
    });

    testWidgets('Settings button is present', (WidgetTester tester) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.settings), findsOneWidget);
    });

    testWidgets('Monitoring button is present', (WidgetTester tester) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      expect(find.byIcon(Icons.analytics), findsOneWidget);
    });

    testWidgets('Monitoring panel opens on button tap', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(AkariProxyApp(initialSettings: testSettings));
      await tester.pumpAndSettle();

      // Tap monitoring button
      await tester.tap(find.byIcon(Icons.analytics));
      await tester.pumpAndSettle();

      // Check monitoring content is visible
      expect(find.text('通信統計'), findsOneWidget);
    });
  });
}

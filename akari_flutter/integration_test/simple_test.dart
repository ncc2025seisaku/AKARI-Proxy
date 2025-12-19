import 'package:flutter_test/flutter_test.dart';
import 'package:akari_flutter/main.dart';
import 'package:akari_flutter/src/rust/frb_generated.dart';
import 'package:akari_flutter/src/services/settings_service.dart';
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async => await RustLib.init());
  testWidgets('App starts with correct title', (WidgetTester tester) async {
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
    expect(find.text('AKARI Proxy'), findsOneWidget);
  });
}

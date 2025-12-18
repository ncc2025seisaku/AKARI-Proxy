import 'package:flutter_test/flutter_test.dart';
import 'package:akari_flutter/main.dart';
import 'package:akari_flutter/src/rust/frb_generated.dart';
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(() async => await RustLib.init());
  testWidgets('App starts with correct title', (WidgetTester tester) async {
    await tester.pumpWidget(const AkariProxyApp());
    expect(find.text('AKARI Proxy'), findsOneWidget);
  });
}

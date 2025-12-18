// Basic widget test for AKARI Proxy Flutter app

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:akari_flutter/main.dart';

void main() {
  testWidgets('AKARI Proxy app smoke test', (WidgetTester tester) async {
    // Build our app and trigger a frame.
    await tester.pumpWidget(const AkariProxyApp());

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

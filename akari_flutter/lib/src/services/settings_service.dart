/// Settings service for persistent storage of user preferences.
///
/// Uses shared_preferences to store and retrieve user settings
/// like remote proxy configuration.
library;

import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

/// User settings for AKARI Proxy.
class AkariSettings {
  final String remoteHost;
  final int remotePort;
  final List<int> psk;
  final bool useEncryption;
  // Content filter settings
  final bool enableJs;
  final bool enableCss;
  final bool enableImg;
  final bool enableOther;

  const AkariSettings({
    required this.remoteHost,
    required this.remotePort,
    required this.psk,
    this.useEncryption = false,
    this.enableJs = true,
    this.enableCss = true,
    this.enableImg = true,
    this.enableOther = true,
  });

  /// Default settings.
  static const defaultSettings = AkariSettings(
    remoteHost: '127.0.0.1',
    remotePort: 9000,
    psk: [116, 101, 115, 116, 45, 112, 115, 107, 45, 48, 48, 48, 48, 45, 116, 101, 115, 116], // "test-psk-0000-test"
    useEncryption: false,
    enableJs: true,
    enableCss: true,
    enableImg: true,
    enableOther: true,
  );

  /// Create settings from JSON map.
  factory AkariSettings.fromJson(Map<String, dynamic> json) {
    return AkariSettings(
      remoteHost: json['remoteHost'] as String? ?? defaultSettings.remoteHost,
      remotePort: json['remotePort'] as int? ?? defaultSettings.remotePort,
      psk: (json['psk'] as List<dynamic>?)?.cast<int>() ?? defaultSettings.psk,
      useEncryption: json['useEncryption'] as bool? ?? defaultSettings.useEncryption,
      enableJs: json['enableJs'] as bool? ?? defaultSettings.enableJs,
      enableCss: json['enableCss'] as bool? ?? defaultSettings.enableCss,
      enableImg: json['enableImg'] as bool? ?? defaultSettings.enableImg,
      enableOther: json['enableOther'] as bool? ?? defaultSettings.enableOther,
    );
  }

  /// Convert settings to JSON map.
  Map<String, dynamic> toJson() {
    return {
      'remoteHost': remoteHost,
      'remotePort': remotePort,
      'psk': psk,
      'useEncryption': useEncryption,
      'enableJs': enableJs,
      'enableCss': enableCss,
      'enableImg': enableImg,
      'enableOther': enableOther,
    };
  }

  /// Create a copy with modified values.
  AkariSettings copyWith({
    String? remoteHost,
    int? remotePort,
    List<int>? psk,
    bool? useEncryption,
    bool? enableJs,
    bool? enableCss,
    bool? enableImg,
    bool? enableOther,
  }) {
    return AkariSettings(
      remoteHost: remoteHost ?? this.remoteHost,
      remotePort: remotePort ?? this.remotePort,
      psk: psk ?? this.psk,
      useEncryption: useEncryption ?? this.useEncryption,
      enableJs: enableJs ?? this.enableJs,
      enableCss: enableCss ?? this.enableCss,
      enableImg: enableImg ?? this.enableImg,
      enableOther: enableOther ?? this.enableOther,
    );
  }

  /// Get PSK as a string (for display purposes).
  String get pskAsString {
    try {
      return String.fromCharCodes(psk);
    } catch (_) {
      return '';
    }
  }

  /// Create PSK from string.
  static List<int> pskFromString(String str) {
    return str.codeUnits;
  }

  @override
  String toString() {
    return 'AkariSettings(remoteHost: $remoteHost, remotePort: $remotePort, useEncryption: $useEncryption)';
  }
}

/// Service for managing persistent settings.
class SettingsService {
  static const _settingsKey = 'akari_settings';
  
  SharedPreferences? _prefs;

  /// Initialize the settings service.
  Future<void> init() async {
    _prefs = await SharedPreferences.getInstance();
  }

  /// Load settings from storage.
  AkariSettings load() {
    if (_prefs == null) {
      return AkariSettings.defaultSettings;
    }

    final jsonString = _prefs!.getString(_settingsKey);
    if (jsonString == null) {
      return AkariSettings.defaultSettings;
    }

    try {
      final json = jsonDecode(jsonString) as Map<String, dynamic>;
      return AkariSettings.fromJson(json);
    } catch (_) {
      return AkariSettings.defaultSettings;
    }
  }

  /// Save settings to storage.
  Future<bool> save(AkariSettings settings) async {
    if (_prefs == null) {
      return false;
    }

    final jsonString = jsonEncode(settings.toJson());
    return _prefs!.setString(_settingsKey, jsonString);
  }

  /// Clear all settings.
  Future<bool> clear() async {
    if (_prefs == null) {
      return false;
    }

    return _prefs!.remove(_settingsKey);
  }
}

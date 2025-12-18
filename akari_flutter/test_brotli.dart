
import 'package:brotli/brotli.dart';
import 'dart:typed_data';

void main() {
  try {
    print("Testing brotli.decode...");
    try { brotli.decode([1, 2, 3]); } catch (e) {}
    
    print("Testing brotliDecode...");
    try { brotliDecode([1, 2, 3]); } catch (e) {}
  } catch (e) {
    print("Error: $e");
  }
}

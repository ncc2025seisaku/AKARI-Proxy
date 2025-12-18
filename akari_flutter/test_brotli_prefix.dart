
import 'package:brotli/brotli.dart' as brotli_lib;

void main() {
  print("Testing brotli_lib.brotli.decode...");
  try {
    // This is likely what we need if we use a prefix
    brotli_lib.brotli.decode([1, 2, 3]);
    print("Success!");
  } catch (e) {
    print("Error: $e");
  }

  print("Testing brotli_lib.brotliDecode...");
  try {
    brotli_lib.brotliDecode([1, 2, 3]);
    print("Success!");
  } catch (e) {
    print("Error: $e");
  }
}

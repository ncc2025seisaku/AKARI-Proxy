plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.akari.akari_flutter"
    compileSdk = flutter.compileSdkVersion
    
    // Get NDK version from local.properties path, environment, or fallback to Flutter default
    val localProps = File(rootProject.projectDir, "local.properties")
    val ndkDir = if (localProps.exists()) {
        java.util.Properties().apply { load(localProps.inputStream()) }
            .getProperty("ndk.dir", "")
    } else ""
    
    // Extract version from ndk.dir path (e.g., /path/to/ndk/29.0.14206865)
    val ndkVersionFromPath = if (ndkDir.isNotEmpty()) {
        File(ndkDir).name.takeIf { it.matches(Regex("\\d+\\.\\d+\\.\\d+")) }
    } else null
    
    ndkVersion = System.getenv("ANDROID_NDK_VERSION") 
        ?: ndkVersionFromPath 
        ?: flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // TODO: Specify your own unique Application ID (https://developer.android.com/studio/build/application-id.html).
        applicationId = "com.akari.akari_flutter"
        // You can update the following values to match your application needs.
        // For more information, see: https://flutter.dev/to/review-gradle-config.
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        release {
            // TODO: Add your own signing config for the release build.
            // Signing with the debug keys for now, so `flutter run --release` works.
            signingConfig = signingConfigs.getByName("debug")
        }
    }
}

flutter {
    source = "../.."
}

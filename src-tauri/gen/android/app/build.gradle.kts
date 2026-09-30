import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("rust")
}

val tauriProperties = Properties().apply {
    val propFile = file("tauri.properties")
    if (propFile.exists()) {
        propFile.inputStream().use { load(it) }
    }
}

// Load keystore properties from src-tauri/gen/android/keystore.properties
val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        keystorePropertiesFile.inputStream().use { load(it) }
    }
}

// Resolve signing values from keystore.properties first, then environment variables (CI)
val releaseStoreFile: String? =
    keystoreProperties.getProperty("storeFile") ?: System.getenv("KEYSTORE_PATH")
val releaseKeyAlias: String? =
    keystoreProperties.getProperty("keyAlias") ?: System.getenv("KEY_ALIAS")
val releaseStorePassword: String? =
    keystoreProperties.getProperty("password") ?: System.getenv("KEYSTORE_PASSWORD")
val releaseKeyPassword: String? =
    keystoreProperties.getProperty("password") ?: System.getenv("KEY_PASSWORD")

val hasReleaseSigning = releaseStoreFile != null &&
    releaseKeyAlias != null &&
    releaseStorePassword != null &&
    releaseKeyPassword != null

android {
    compileSdk = 36
    namespace = "com.robin.BusMitra"

    signingConfigs {
        create("release") {
            if (hasReleaseSigning) {
                storeFile = file(releaseStoreFile!!)
                storePassword = releaseStorePassword
                keyAlias = releaseKeyAlias
                keyPassword = releaseKeyPassword
            }
        }
    }

    defaultConfig {
        manifestPlaceholders["usesCleartextTraffic"] = "false"
        applicationId = "com.robin.BusMitra"
        minSdk = 24
        targetSdk = 36
        versionCode = tauriProperties.getProperty("tauri.android.versionCode", "1").toInt()
        versionName = tauriProperties.getProperty("tauri.android.versionName", "1.0")
    }

    buildTypes {
        getByName("debug") {
            manifestPlaceholders["usesCleartextTraffic"] = "true"
            isDebuggable = true
            isJniDebuggable = true
            isMinifyEnabled = false
            packaging {
                jniLibs.keepDebugSymbols.add("*/arm64-v8a/*.so")
                jniLibs.keepDebugSymbols.add("*/armeabi-v7a/*.so")
                jniLibs.keepDebugSymbols.add("*/x86/*.so")
                jniLibs.keepDebugSymbols.add("*/x86_64/*.so")
            }
        }
        getByName("release") {
            if (hasReleaseSigning) {
                signingConfig = signingConfigs.getByName("release")
            }
            isMinifyEnabled = true
            proguardFiles(
                *fileTree(".") { include("**/*.pro") }
                    .plus(getDefaultProguardFile("proguard-android-optimize.txt"))
                    .toList().toTypedArray()
            )
        }
    }

    kotlinOptions {
        jvmTarget = "1.8"
    }

    buildFeatures {
        buildConfig = true
    }
}

// Fail with a clear message when a release build is requested without signing info
gradle.taskGraph.whenReady {
    val isReleaseBuild = allTasks.any { it.name.contains("Release", ignoreCase = true) }
    if (isReleaseBuild && !hasReleaseSigning) {
        throw GradleException(
            "Release signing is not configured. Create keystore.properties in " +
                "src-tauri/gen/android/ with keyAlias, password and storeFile " +
                "(absolute path), or set KEYSTORE_PATH, KEY_ALIAS, KEYSTORE_PASSWORD " +
                "and KEY_PASSWORD environment variables."
        )
    }
}

rust {
    rootDirRel = "../../../"
}

dependencies {
    implementation("androidx.webkit:webkit:1.14.0")
    implementation("androidx.appcompat:appcompat:1.7.1")
    implementation("androidx.activity:activity-ktx:1.10.1")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.lifecycle:lifecycle-process:2.10.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test.ext:junit:1.1.4")
    androidTestImplementation("androidx.test.espresso:espresso-core:3.5.0")
}

apply(from = "tauri.build.gradle.kts")
package com.robin.BusMitra

import android.os.Bundle
import androidx.activity.enableEdgeToEdge
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat

class MainActivity : TauriActivity() {
  override fun onCreate(savedInstanceState: Bundle?) {
    enableEdgeToEdge()
    super.onCreate(savedInstanceState)

    val windowInsetsController = WindowCompat.getInsetsController(window, window.decorView)

    // Hides both the top status bar and bottom navigation buttons
    windowInsetsController.hide(WindowInsetsCompat.Type.systemBars())

    // Allows users to temporarily reveal system bars with a screen edge swipe
    windowInsetsController.systemBarsBehavior =
      WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
  }
}
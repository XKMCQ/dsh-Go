// 车机 (car head units): what a build changes about the window when it targets one.
//
// A head unit is a fixed landscape slab: wide and often short — 1280 × 480 at
// hdpi is an 853 × 320 window — with no soft keyboard folded over the bottom
// half and no status bar worth the space. The layout's own rule ("under 480
// tall is a phone on its side") is written for a phone held sideways, so car
// mode turns it off and lets the columns follow the width alone.
//
//   tooling/build-apk.sh -f x64 --no-companion -- --dart-define=DSH_CAR=1
//
// docs/car-x86_64.md has the whole recipe: the x86_64 runtime, the APK, what
// the unit has to allow, and the checks to run on the device.

import 'package:flutter/services.dart';

import '../ui/shell/adaptive/adaptive_layout.dart';

/// `--dart-define=DSH_CAR=1`: this build is for a car head unit.
const bool dshCarMode = bool.fromEnvironment('DSH_CAR');

/// `--dart-define=DSH_CAR_LANDSCAPE=1`: pin the UI to landscape.
///
/// Off by default: rotating units (BYD-style) run portrait half the time, and
/// the window class follows whatever the unit hands us. On a unit whose ROM
/// mis-guesses the orientation, turn this on.
const bool dshCarLandscape = bool.fromEnvironment('DSH_CAR_LANDSCAPE');

/// Applies the car shape before the first frame. A no-op on phones.
Future<void> applyCarMode() async {
  if (!dshCarMode) return;
  // Read by WindowClass.of (lib/ui/shell/adaptive/adaptive_layout.dart).
  WindowClass.carMode = true;
  if (dshCarLandscape) {
    await SystemChrome.setPreferredOrientations(const [
      DeviceOrientation.landscapeLeft,
      DeviceOrientation.landscapeRight,
    ]);
  }
}

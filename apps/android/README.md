# Sparta for Android

Native Android client for **Sparta** ("Your calls. Your voice. Your shield."), the multilingual AI call-screening
assistant. Kotlin, Jetpack Compose (Material 3), Hilt, Room, WorkManager, Retrofit/OkHttp, kotlinx.serialization.

**What it really does on a phone:** it becomes the Android *call-screening app* (`ROLE_CALL_SCREENING`, Android 10+),
decides in well under the platform deadline whether an incoming call rings, is silenced or is rejected (local rules and
synced block/trust lists, no network on the fast path), tells you what it did, shows your call history and the
backend's analysis of calls that reached the Sparta telephony number, and lets you configure everything.

**What it cannot do (the platform does not allow it):** answer an ordinary phone call, speak to the caller, hear or
record call audio. The AI conversation only exists for calls that reach the *backend's* telephony number (carrier call
forwarding) and only to the extent the backend's provider reports (`CallDetail.capabilities`). The app never implies
more than that.

## Build and test

Windows (PowerShell), from this directory:

```powershell
.\gradlew.bat assembleDebug          # app\build\outputs\apk\debug\app-debug.apk
.\gradlew.bat testDebugUnitTest      # JVM + Robolectric tests, including the Compose UI tests
.\gradlew.bat lintDebug
.\gradlew.bat assembleRelease        # R8-minified, unsigned unless you provide signing material
```

macOS/Linux use `./gradlew`. Prerequisites, backend configuration, the role set-up steps, the permission table, the test
matrix and the honest list of limitations are in [`docs/ANDROID_SETUP.md`](../../docs/ANDROID_SETUP.md).

## Layout

| Path (`app/src/main/kotlin/io/github/snowjug/sparta`) | Purpose |
| --- | --- |
| `core/` | Pure Kotlin rules with unit tests: number normalisation, masking and fingerprinting, the screening decision engine and its deadline/respond-once coordinator, live-event reducer, deep links, routes, backend URL policy |
| `screening/` | `SpartaCallScreeningService` and the Android-free `ScreeningCallHandler` (watchdog, fail-open) |
| `data/` | Retrofit API + DTOs (tolerant of unknown fields/enums), Room (history, lists, cache), DataStore settings, repositories, WebSocket client |
| `platform/` | Android adapters: role, permissions, notifications, contacts, device info |
| `work/` | WorkManager upload and periodic sync (no foreground service) |
| `ui/` | Compose theme, shared components and the screens: onboarding, protection status, incoming-call intelligence, live call, recent calls, call detail, Assistant Studio, privacy and safety, diagnostics |

UI tests live in `app/src/sharedTest` and run both under Robolectric (`testDebugUnitTest`) and, on a device or
emulator, as instrumented tests.

Signing keys, `local.properties` and build outputs are never committed (see `.gitignore`).

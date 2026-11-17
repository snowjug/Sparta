# Sparta for Android: setup, behaviour and honest limits

The Android app lives in [`apps/android`](../apps/android). This document is the single place for prerequisites,
building, role set-up, permissions, backend configuration, tests, and a candid list of what is **not** verified.

## 1. What the app is, and what it can never be

| It does | It cannot do (the platform does not allow it) |
| --- | --- |
| Becomes your **call-screening app** (`RoleManager.ROLE_CALL_SCREENING`, Android 10+). For each incoming call Android asks `SpartaCallScreeningService`, which answers **allow**, **silence the ringer** or **reject** from local rules and synced block/trust lists, within its own 1.5 s budget (2.5 s watchdog, Android's limit is about 5 s). | Answer an ordinary phone call, speak to the caller, or hear / record call audio. A `CallScreeningService` gets call *metadata* only. |
| Tells you what it did (notification + history), masks every number (`+91 98•••• ••21`) and keeps only a keyed fingerprint of it. | Show its own UI over the system incoming-call screen. |
| Shows the backend's analysis, transcript, risk evidence, summary and owner controls for calls that **reach the backend's telephony number** (carrier call forwarding), and lets you give feedback, block or trust. | Make an AI conversation happen on a normal call. That exists only when the call reaches the backend, and only to the extent the backend's provider reports in `CallDetail.capabilities` (`two_way_audio`, `simulated`, `takeover_note`). The app reads those flags and never claims more. |

Every simulated thing is labelled "Simulated". "Screened on this phone" calls say they have no transcript, no analysis and
no live controls. There is no call recording anywhere in the app.

## 2. Prerequisites

* **JDK 17** (`JAVA_HOME`).
* **Android SDK** with `platforms;android-36` and `build-tools;36.0.0`; licences accepted. Point Gradle at it with
  `ANDROID_HOME` or an untracked `apps/android/local.properties` (`sdk.dir=...`).
* Network access to Google Maven, Maven Central and the Gradle plugin portal (first build downloads dependencies).
* No global Gradle is needed: the wrapper pins **Gradle 9.5.0** (distribution checksum pinned).
* Toolchain that builds and is tested: AGP 9.3.1, Kotlin 2.4.21 (built-in Kotlin), KSP, Hilt 2.60.1, Room 2.8.5,
  Compose BOM 2026.06.01, `compileSdk`/`targetSdk` 36, `minSdk` 26. (Compose BOM 2026.09 needs `compileSdk` 37, which is not
  installed here, hence the pinned BOM.)

## 3. Build, install, run

From `apps/android` (Windows PowerShell shown; use `./gradlew` elsewhere):

```powershell
.\gradlew.bat assembleDebug        # app\build\outputs\apk\debug\app-debug.apk
.\gradlew.bat assembleRelease      # R8-minified and resource-shrunk; unsigned unless signing material is supplied
.\gradlew.bat bundleRelease        # app\build\outputs\bundle\release\app-release.aab (same rules)
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

**Release signing.** Signing material is never committed. Provide an untracked `apps/android/keystore.properties`
(`storeFile`, `storePassword`, `keyAlias`, `keyPassword`) or the environment variables `SPARTA_KEYSTORE_FILE`,
`SPARTA_KEYSTORE_PASSWORD`, `SPARTA_KEY_ALIAS`, `SPARTA_KEY_PASSWORD`. Without them `assembleRelease` produces an unsigned
APK, which Android will not install.

## 4. Backend configuration

The app talks to **one** owner-configured backend (`docs/API_CONTRACT.md`). Set it in onboarding ("Connect your Sparta
backend") or later under *Privacy → Backend*. The app first probes `GET /api/v1/system/status` (read-only), then saves the
address and pulls `GET /screening/config` (the fingerprint key, forwarding number, policy) and `GET /screening/lists`.

| Build | Allowed addresses | Why |
| --- | --- | --- |
| **release** | `https://` only (network security config forbids cleartext) | production safety |
| **debug** | `https://`, plus `http://` for `localhost`, `10.0.2.2` (emulator's host loopback), private LAN ranges and `*.local` | local development. Android's network-security config cannot express "LAN only", so debug allows cleartext as a whole and `BackendUrlPolicy` (unit-tested) restricts what can be saved. |

The debug build pre-fills `http://10.0.2.2:8000/`.

* **Emulator → backend on the host:** start the API (`python -m sparta serve` from `services/api`, default port 8000, with
  `SPARTA_ENV=development`) and use `http://10.0.2.2:8000/`.
* **Physical device:** use `http://<your-LAN-IP>:8000/`, or `adb reverse tcp:8000 tcp:8000` and `http://localhost:8000/`.
* The `ws_url` returned by `POST /live/ticket` is **ignored on purpose**: the WebSocket URL is built from the configured
  address, so a live ticket can only ever be presented to the backend you chose.

**Authentication.** Development backends need no credentials and report `dev_banner: true`; the app then shows a
"Development identity" strip on every screen. For production the app has a pluggable `AuthTokenProvider` (sends
`Authorization: Bearer ...` when it returns a token). **Real OIDC / Microsoft Entra External ID sign-in is NOT implemented
and was NOT verified**: the provider is `NoAuthTokenProvider`, so a production backend answers 401 and the app reports it.

## 5. Turning call screening on (role set-up)

1. Install the app on **Android 10 or newer** (`minSdk` is 26, but the screening role does not exist before Android 10:
   Status says so and nothing is broken).
2. Open Sparta → onboarding step "Let Sparta screen your calls" → **Choose Sparta as call-screening app** (or, later,
   Status → *Turn on call screening*). Android shows its own role dialog; pick Sparta.
3. If you decline, the app explains and offers *Try again* and a shortcut to the default-apps settings (the wording differs
   between phone makers: usually Settings → Apps → Default apps → *Caller ID & spam app*).
4. Verify: Status shows **"Screening is on"** (the role is re-read every time the screen resumes, because the OS can change it).

Optional, for live AI audio only: ask your carrier to forward unanswered calls to the backend's number. The app can only
**pre-fill the dialer** with a standard GSM conditional-forwarding code (`**61*<number>#`, `**67*`, `**62*`; cancel with
`##002#`); you review it and press call. The number is validated to digits only. Android cannot tell the app whether
forwarding is active, so the app says "cannot tell whether it is on" and never claims it is.

## 6. Permissions and why

Nothing is requested before the screen has explained why; the system prompt appears only when you press a button, and every
refusal has a graceful path (explanation, retry where Android allows it, a shortcut to settings when it does not).

| Permission / role | Kind | Why Sparta needs it | When it is requested | If refused |
| --- | --- | --- | --- | --- |
| `ROLE_CALL_SCREENING` (service permission `BIND_SCREENING_SERVICE`, held by the system) | system role | So Android asks Sparta about each incoming call | Button in onboarding / Status → system role dialog | Screening stays off; the rest of the app works |
| `INTERNET` | normal | Talk to **your** backend only | install time | n/a |
| `ACCESS_NETWORK_STATE` | normal | Added for WorkManager so its "only when there is a network" constraint can be checked (background sync and uploads) | install time | n/a |
| `WAKE_LOCK` | normal | Added for WorkManager: keeps the CPU awake for the few seconds a sync or upload runs. The app takes no wake lock of its own | install time | n/a |
| `RECEIVE_BOOT_COMPLETED` | normal | Added for WorkManager: re-registers the periodic sync after a reboot | install time | n/a |
| `POST_NOTIFICATIONS` | runtime (Android 13+), optional | Tell you a call needs your decision and when Sparta silenced or blocked a caller | "Allow notifications" button, after an explanation | Decisions are visible in the app only; Status/Privacy say so and link to settings when Android will not ask again |
| `READ_CONTACTS` | runtime, optional, **off by default** | Only to ask Android "is this number in my contacts?" so saved contacts can ring. No names/numbers are read back, copied or uploaded | Only when you switch on *Treat saved contacts as known callers* (the explanation sits above the switch) | The option stays off; unknown-caller rules apply |

The three WorkManager rows are normal permissions (no prompt, no user-visible capability); they are declared explicitly in
the manifest with the reason next to them. AndroidX also adds an internal, signature-level
`<package>.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION` that protects the app's own dynamic receivers; it grants nothing to
other apps.

**Never requested:** microphone, phone state, call log, answer-calls, call-phone (the forwarding helper uses `ACTION_DIAL`,
which needs none), storage, location. There is **no foreground service**: nothing in the app could justify one, so
WorkManager's `FOREGROUND_SERVICE` permission and its `SystemForegroundService` are removed from the merged manifest
(`tools:node="remove"`), and Sparta's jobs never ask for expedited or foreground work. Check it yourself: the merged manifest
is `app/build/intermediates/merged_manifests/release/processReleaseManifest/AndroidManifest.xml`.

## 7. Notifications, deep links and what runs in the background

* Two channels: **Calls that need you** (high importance) and **Screening decisions** (default). The lock screen only ever
  shows a generic title; the masked number and any quoted lines appear after unlocking, and quoted lines are optional
  (*Privacy → Notifications → Show what the caller said*). Quiet hours are honoured.
* Tapping a notification opens `sparta://call/{id}` (incoming-call intelligence) or `sparta://event/{id}` (a decision made
  on this phone). Also supported: `sparta://call/{id}/detail` and `sparta://call/{id}/live`. The id is validated
  (`[A-Za-z0-9_-]{1,64}`), never trusted.
* **While the app is open** a WebSocket to the backend turns `escalation.requested` into a notification instantly. It is
  stopped when the UI stops. **While it is closed** alerts come from a WorkManager job that runs about every 30 minutes
  (network + battery-not-low constraints). **Instant push alerts (FCM) are not set up**, so an escalation raised while the
  app is closed can arrive late; a live call is usually over by then.
* Screening events are uploaded idempotently (`client_event_id`) by WorkManager with exponential backoff.

## 8. Privacy by design

* The device never sends or stores a raw number. It stores/sends a masked display and `HMAC-SHA256(key = base64(fingerprint_salt), message = E.164)`
  (algorithm taken from the backend and unit-tested against independently computed vectors).
* Backup and device transfer are disabled for the app's data (`data_extraction_rules`, `allowBackup=false`).
* *Privacy → Your data*: transcript retention, "keep full caller numbers" (backend-side, off by default), delete history
  on this phone, delete all call data (backend first, then the phone).

## 9. Tests

```powershell
.\gradlew.bat testDebugUnitTest      # everything below, on the JVM
.\gradlew.bat lintDebug              # 0 errors; remaining warnings are dependency/SDK version hints (see below)
.\gradlew.bat assembleDebug assembleRelease
.\gradlew.bat connectedDebugAndroidTest   # needs a device or emulator: see "not run" below
```

Lint is clean of errors and needs no baseline file. Its remaining warnings are version-currency hints
(`GradleDependency`, `NewerVersionAvailable`, `AndroidGradlePluginVersion`, `OldTargetApi`): newer library, Gradle, AGP and
`compileSdk` 37 releases exist, but the toolchain is deliberately pinned to the combination that was built and tested here
(`compileSdk` 37 is not installed). Update them together, then re-run the whole suite.

Results of the last full run are in §11. What the tests cover (and the brief's "Android tests" list):

| Area | Where |
| --- | --- |
| Role enrolment, unsupported OS, role missing, declined | `ProtectionContentTest`, `OnboardingContentTest`, `ProtectionViewModelTest`, `OnboardingViewModelTest`, `RoleStateMapperTest` |
| Screening decision path | `ScreeningDecisionEngineTest`, `LocalFactsGathererTest`, `ScreeningCoordinatorTest`, `ScreeningResponsesTest` |
| Service deadline / respond exactly once / fail open | `ScreeningCoordinatorTest`, `ScreeningCallHandlerTest` (watchdog, late decision cannot answer twice, dependency failure, cancelled scope), `SpartaCallScreeningServiceTest` (real service class under Robolectric) |
| Permission denial | `OnboardingContentTest`, `PrivacyContentTest`, `OnboardingViewModelTest`, `PrivacyViewModelTest`, `ProtectionViewModelTest`, `PermissionStatesTest` |
| Notifications and deep links | `AndroidNotifierTest` (channels, lock-screen privacy, permission gating, tap → `DeepLinks.parse` → `Routes.forLink`), `DeepLinksTest`, `RoutesTest` |
| Call detail, honesty, owner controls | `CallDetailContentTest`, `IncomingContentTest`, `LiveCallContentTest`, `OwnerControlsTest`, `AudioHonestyTest`, `CallDetailViewModelTest`, `LiveCallViewModelTest` |
| Preferences | `PreferencesRepositoryTest`, `PrivacyViewModelTest`, `StudioViewModelTest`, `PrivacyContentTest`, `StudioContentTest` |
| Recent calls, filters, two-pane layout | `CallsContentTest`, `CallsViewModelTest`, `AdaptiveLayoutTest` |
| Battery / WorkManager | `UploadWorkerTest`, `WorkSchedulerTest`, `UploadWorkPolicyTest`, `AppViewModelTest` (one periodic job, only while useful) |
| Accessibility rules | `AccessibilityTest` opens every screen (and every onboarding step) and asserts that each interactive element has an accessible name and a touch target of at least 48 dp, and that each screen has headings; live regions, roles and content descriptions are asserted in the per-screen `*ContentTest`s; WCAG contrast of the palette in `ContrastTest`; reduced motion in `VoiceVisualizerSpecTest`, `ReducedMotionTest`. These are structural checks under Robolectric: they are **not** a TalkBack session on a device |
| Wire contract | `DtoDeserializationTest`, `SpartaApiClientTest` (MockWebServer), `LiveCallClientTest`, fixtures under `src/test/resources/fixtures` (unknown fields and enum values are tolerated) |

UI tests live in `app/src/sharedTest` and run **under Robolectric** (`testDebugUnitTest`). The same sources are also compiled
into the instrumented APK (`compileDebugAndroidTestKotlin`) so they can run on a device or emulator.

## 10. Honest limitations and unverified items

* **Real call screening was never exercised on a physical device or an emulator.** The decision logic, the service class
  (under Robolectric), the response mapping and the deadline behaviour are tested; the system actually binding the service
  and honouring silence/reject is not.
* **No emulator ran here**, so no instrumented test has been executed. The machine's emulator hardware acceleration is not
  usable (Windows Hypervisor Platform is disabled and no emulator/system image is installed). Everything UI-related was
  verified under Robolectric only; layout on real screens, TalkBack behaviour and OEM-specific quirks (battery managers,
  default-app settings wording, call-screening role handling on Samsung/Xiaomi/etc.) are **unverified**.
* **No push notifications** (see §7).
* **Real OIDC sign-in is not implemented or verified** (see §4).
* The first-party **release build** is minified by R8 and builds, but was **not run on a device**; R8 correctness at runtime is unverified.
* `silence` needs Android 10+; STIR/SHAKEN verification status needs Android 11+ and carrier support (otherwise reported as unknown).
  A rejected call is answered with "disallow + reject" and Android's own missed-call notification is skipped (Sparta posts
  its own, with the reason); Sparta deliberately does **not** ask Android to hide the call from the system call log, so a
  rejected call stays visible in the phone's call history.
* Carrier call forwarding codes are standard, but carriers differ and Android exposes no API to read forwarding state.
* The UI is **English only** (all copy is in `strings*.xml`, so translation is possible; the short failure messages that the
  data layer produces, such as "The backend could not be reached.", are still plain English constants and would need to be
  moved to resources first). The assistant's *spoken* languages (English, Hindi/Hinglish, Kannada/Kanglish) are a backend
  capability.
* Backend end-to-end behaviour (real `/screening/*`, `/calls/*`, WebSocket) was tested against fixtures and MockWebServer, built
  from `docs/API_CONTRACT.md` and the Python models, not against the running API unless stated in the final report.
* The personal (cloned) voice cannot be enrolled from the phone: consent and provider approval are out of scope here, and the
  Studio says so.

## 11. Verification log

Last verified on Windows 11 with JDK 17, Gradle 9.5.0 and AGP 9.3.1, from `apps/android` (re-run these to refresh):

| Command | Result |
| --- | --- |
| `.\gradlew.bat testDebugUnitTest` | BUILD SUCCESSFUL: 64 test classes, **624 tests, 0 failures, 0 skipped** (includes the 209 Compose UI tests that run under Robolectric and 94 ViewModel tests) |
| `.\gradlew.bat lintDebug` | BUILD SUCCESSFUL: **0 errors, 21 warnings** (all dependency/SDK version hints, see §9); no baseline file |
| `.\gradlew.bat compileDebugAndroidTestKotlin` | BUILD SUCCESSFUL: the shared UI tests compile into the instrumented APK. **Not run**: no device or emulator |
| `.\gradlew.bat assembleDebug assembleRelease bundleRelease` | BUILD SUCCESSFUL. `app-debug.apk` 21.6 MiB, `app-release-unsigned.apk` 2.4 MiB (R8 minified and resource-shrunk), `app-release.aab` 5.3 MiB |

Not run, because no suitable device exists in the build environment: the release build on a device, `connectedDebugAndroidTest`,
real call screening, TalkBack, push, real OIDC sign-in, and an end-to-end session against the running backend (see §10).

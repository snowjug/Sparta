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

**Local SIP (Phase 3) and this app.** Sparta can now take a *voice* call from a SIP phone on your own network through a local
Asterisk (`TELEPHONY_PROVIDER=asterisk`, [TELEPHONY.md](TELEPHONY.md) section 4.5). This app does **not** place or answer that call:
a separate SIP app (Linphone, an open-source client) does, and the Sparta app is where you then watch it. For such a call the app
shows the provider as **Local SIP (Asterisk)**; the web app shows `Connection: Local SIP`, `PSTN: Not configured` and a Take over
that rings a SIP extension. Nothing about local SIP lets a normal mobile or landline call reach Sparta. The Linphone set-up and test
script are in [ANDROID_SIP_TESTING.md](ANDROID_SIP_TESTING.md); it is a checklist that has **not been run on a phone**. The app's
Protection and Diagnostics rows show the raw provider string for it, and `status_live_calls_yes` still says "forwarded calls";
these wording details were left alone on purpose in Phase 3.

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

## Physical-device validation checklist (NOT YET RUN)

**Nothing in this section has been run on a physical phone.** When it was written no phone was attached to the build
machine, no emulator package or system image was installed and no AVD existed (§10), so every **Result** below says
`NOT RUN`. The *Expected result* column states what the code is written to do: it is a prediction for a person with a
phone to confirm or refute, not a finding. The automated tests (§9, §11) run on the JVM under Robolectric and say nothing
about real Android behaviour. When every row has been run by a person, rename this section and refresh §10 and §11.

**Prerequisites**

* **Phone:** a physical phone on **Android 10 or newer** (API 29+; `ROLE_CALL_SCREENING` does not exist before it, so rows
  2 and 13 cannot pass on Android 9 or lower, where Status says so) with a **working SIM** (tablets and Wi-Fi-only devices
  are not offered the role). Rows 4a and 4b need **Android 13+**; on Android 10–12 the expected result there is "Not needed
  on this Android version". Record the model, Android release and API level with `adb shell getprop ro.product.model`,
  `adb shell getprop ro.build.version.release` and `adb shell getprop ro.build.version.sdk`. Do not record serial numbers,
  the IMEI or your own phone number.
* **A second phone or line you control** to place the test calls from. Never use a stranger's or a customer's number.
* **USB debugging** on (Settings → Developer options), the PC authorised (accept the prompt on the phone) and `adb` from
  the SDK's `platform-tools` on `PATH`. Always list devices first and check that the phone you mean is `device` (not
  `unauthorized` or `offline`): `adb devices`. With more than one device add `-s <serial>` to every `adb` command below.
* **Install the debug build** from `apps/android` (§3): `.\gradlew.bat assembleDebug`, then
  `adb install -r app\build\outputs\apk\debug\app-debug.apk`. It is signed with the automatic debug key, which is enough
  here; a release APK needs the signing material of §3 and is not covered. Note `git rev-parse --short HEAD` and
  `Get-FileHash app\build\outputs\apk\debug\app-debug.apk` with your results.
* **Point the app at a backend.** Start the API on the PC with the simulator (`SPARTA_ENV=development`, from
  `services/api`: `python -m sparta serve`, port 8000; the simulator is on by default). For a phone on USB use
  `adb reverse tcp:8000 tcp:8000` and enter `http://localhost:8000/` as *Backend address* (onboarding step "Connect your
  Sparta backend", or Privacy → Backend). Do **not** keep the pre-filled `http://10.0.2.2:8000/`: that address only exists
  inside the Android emulator. A LAN address (`http://<PC-LAN-IP>:8000/`, accepted by the debug build) only works if the
  API is started on that address **and** with `SPARTA_ALLOW_NETWORK_DEV_AUTH=true`, because the development identity
  refuses a non-loopback bind otherwise (`services/api/src/sparta/cli.py`). That setting lets anyone on the network act as
  the owner, so use it only on a trusted network, or stay with `adb reverse`.
* **A simulated escalation** (rows 6–8, 12 and 15–17): the curated scenario `delivery-legit` ("Delivery executive at the
  gate", expected action `escalate_to_owner`) is played by the backend simulator. Start it from the web app's Simulator Lab
  or from PowerShell, and keep the call id (it is not a phone number). If a call has ended, start another one:

  ```powershell
  $call = Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/simulator/calls -ContentType 'application/json' -Body '{"scenario_id":"delivery-legit","autoplay":true}'
  $call.id
  ```

  To watch a call slowly, create it without `autoplay` and send the caller lines yourself (`docs/API_CONTRACT.md`,
  `POST /calls/{id}/turns`).
* **Evidence helpers.** Sparta's own code writes no log lines, but the system and libraries may log numbers, so only keep
  excerpts produced like this, and read them before saving:

  ```powershell
  $spartaPid = (adb shell pidof -s io.github.snowjug.sparta).Trim()      # the app must be running
  adb logcat -d --pid=$spartaPid | ForEach-Object { $_ -replace '\d{5,}', '#####' }
  adb logcat -d -b crash | ForEach-Object { $_ -replace '\d{5,}', '#####' }
  ```

* **Not covered:** the instrumented tests. `.\gradlew.bat assembleDebugAndroidTest` currently **fails** at
  `:app:dexBuilderDebugAndroidTest`: D8 refuses the backtick-quoted test names that contain spaces (179 function names in
  `app/src/sharedTest`; "Space characters in SimpleName … are not allowed prior to DEX version 040", and `minSdk` is 26),
  although `compileDebugAndroidTestKotlin` passes. Names without spaces avoid it. So `connectedDebugAndroidTest` cannot be
  run until that is fixed, and no row below depends on it.

| # | Check | Exact steps | Expected result (what a PASS looks like) | Result (fill in) | Evidence (sanitised) |
| --- | --- | --- | --- | --- | --- |
| 1 | Debug (or internal-test) build installs and starts | 1) `adb devices`: the phone is listed as `device`.<br>2) `adb install -r app\build\outputs\apk\debug\app-debug.apk`.<br>3) Open **Sparta** from the launcher. | `adb` prints `Success`. The app opens on onboarding without a crash or an "isn't responding" dialog and shows the Welcome step (onboarding has five: Welcome, Backend, Role, Permissions, Forwarding). | NOT RUN | Record: the `adb install` output, model / Android release / API level, APK SHA-256 and commit, a screenshot of the Welcome step. |
| 2 | Call-screening role enrolment | 1) Onboarding step "Let Sparta screen your calls" → **Choose Sparta as call-screening app** (later: Status → **Turn on call screening**).<br>2) In Android's own dialog choose Sparta and confirm.<br>3) Settings → Apps → Default apps → **Caller ID & spam app** (some makers: *Call screening app*): read which app is selected.<br>4) Back in Sparta open Status. Optional cross-check: `adb shell cmd role get-role-holders android.app.role.CALL_SCREENING`. | The dialog is Android's (Sparta draws none). Settings lists Sparta. Status shows "Screening is on" (headline and pill) with "Sparta screens incoming calls on this phone…"; Diagnostics → *Call-screening role* agrees. The role is re-read whenever Status resumes: go to Settings and back, nothing stale. | NOT RUN | Record: screenshots of the system dialog, the Default apps screen and Status (no numbers on any of them); optional role-holder output. |
| 3 | Denied-role behaviour | 1) On a phone where Sparta does not hold the role: Status → **Turn on call screening**; cancel the system dialog (or press Back).<br>2) Read the role card; tap **Try again**; cancel again.<br>3) Tap **Open default app settings**.<br>4) Repeat in onboarding step "Let Sparta screen your calls" and finish onboarding.<br>5) Grant the role from Android's Default apps screen and return to Sparta. | Nothing crashes. Status keeps "Screening is off" and explains "You declined the system request. You can try again, or choose Sparta under Settings, Apps, Default apps…" with **Try again** and **Open default app settings** (Android's default-apps page, or the main Settings if the phone has none). Onboarding says "You declined. You can continue without screening and turn it on later from the Status tab." and can be finished. After step 5, Status flips to "Screening is on" on return. | NOT RUN | Record: screenshots of the declined role card and the onboarding message. |
| 4a | Notification permission granted (Android 13+) | 1) Fresh install. Reach onboarding step "Notifications" (or Status → **Allow notifications**) and check that no system prompt has appeared yet.<br>2) Read the explanation, tap **Allow notifications**, choose **Allow**.<br>3) Settings → Apps → Sparta → Notifications: look at the channels. | The system prompt appears only after the button press. Then "Notifications are allowed." is shown, the "Notifications are off" card is gone from Status and Diagnostics → Permissions says "Allowed". Two channels exist: **Calls that need you** (high importance) and **Screening decisions** (default). On Android 10–12 there is no prompt and Diagnostics says "Not needed on this Android version". | NOT RUN | Record: screenshots of the step or card, Diagnostics → Permissions and the channel list. |
| 4b | Notification permission denied (Android 13+) | 1) Fresh install (uninstall first if row 4a already ran). Tap **Allow notifications**, choose **Don't allow**; read the screen.<br>2) Tap **Allow notifications** again, **Don't allow** again; read the screen.<br>3) Tap **Open notification settings**.<br>4) With notifications denied run row 6 and row 13. | After the first refusal: Status shows "Notifications are off" with **Allow notifications**; onboarding says "Notifications are off. You can enable them later in the system settings." After the second: "Android will not ask again. Open the system settings to allow notifications." with **Open notification settings**, which opens Sparta's notification settings. No notification is posted for the escalation or the screened call, nothing crashes, and the decisions still appear in Calls and in Status → Last screening decision. | NOT RUN | Record: screenshots of both states and of the Calls tab showing the decision. |
| 5a | Backend connection | 1) Start the API and `adb reverse` (see prerequisites).<br>2) Privacy → Backend (or onboarding "Connect your Sparta backend"): type `http://localhost:8000/` in **Backend address**.<br>3) Tap **Test connection**, then **Use this backend**.<br>4) Open Status → Backend and Diagnostics → Backend. | "Connected. Backend version …, telephony provider: simulator." plus "This backend is running a simulator: no real phone calls reach it." and, for a development backend, the "Development identity" strip on every screen. **Use this backend** gives "Backend saved."; Status shows "Connected (…)"; Diagnostics shows the version, provider and sign-in mode, and no "Last sync problem". In this debug build an `http://` address on a public host is refused ("This build only connects over HTTPS…"). | NOT RUN | Record: screenshots of the test result and the Status → Backend card (the address is not a phone number; mask any public host name). |
| 5b | Backend down: error state | 1) With the backend connected, stop the API (Ctrl+C) or run `adb reverse --remove tcp:8000`.<br>2) Status → **Refresh status**.<br>3) Calls tab: pull down to refresh.<br>4) Diagnostics → **Test the connection**; try an owner action on a call.<br>5) Restore the backend and refresh Status. | Status → Backend: "Not reachable: The backend could not be reached. Showing the last known status." Calls keeps the saved calls and says "Showing saved calls. Could not refresh: The backend could not be reached." Diagnostics reports the failure; owner actions fail with the same message and claim no success. Nothing crashes. Row 13 still works (screening uses local data only). After recovery Status says "Connected (…)" and the Calls banner is gone. | NOT RUN | Record: one screenshot per state. |
| 6 | Notification arrives for a simulated escalation (a local notification: there is no FCM push, §7) | Prerequisites: onboarding finished, backend connected, row 4a done, quiet hours off.<br>**A, app open:** keep Sparta open on Status and start `delivery-legit`.<br>**B, app closed:** swipe Sparta away from Recents (do not use *Force stop*: it suspends background work until the next manual launch), start a **new** `delivery-legit` call, then wait for the background sync (about every 30 minutes with a 10-minute flex, network and battery-not-low required, later in Doze) or open Sparta → Diagnostics → **Run a sync now**.<br>**C:** lock the phone and look at the notification. | A: a **Calls that need you** notification appears within seconds. Title "Sparta needs you on a call" (or "Sparta flagged a high-risk call"); text "A call from `<masked number>` needs your decision." or "`<masked number>`: `<purpose>`" (the app masks the number itself). B: it arrives only with the next sync pass, minutes later, or when forced (Diagnostics: "Sync finished… Notifications posted: 1"); being late is not a failure, record the delay. C: the lock screen shows only "Sparta", the number and purpose appear after unlocking. Each call notifies at most once (running the sync again posts nothing new). | NOT RUN | Record: screenshots of the notification (number masked), of the lock screen and of the Diagnostics sync line, plus the delay in minutes for B. |
| 7 | Tapping it deep-links to the call, and on to the live call | 1) Tap the notification from row 6 with Sparta in the background, then again after swiping Sparta away from Recents.<br>2) On the screen that opens, tap **Watch live** (shown only while the call is active).<br>3) By hand, with the call id: `adb shell am start -W -a android.intent.action.VIEW -p io.github.snowjug.sparta -d "sparta://call/<callId>/live"`; repeat with `.../<callId>/detail`, with `sparta://call/<callId>` and with `sparta://event/<eventId>` (an id from a "Decision on this phone" row).<br>4) Negative: `sparta://call/<callId>/bogus` and `sparta://call/not%20valid`. | The notification opens **Call intelligence** (`sparta://call/{id}`: "Sparta needs your decision", masked caller, evidence, controls), **not** the live screen; **Watch live** then opens **Live call**. By hand: `/live` opens Live call, `/detail` opens Call details, no suffix opens Call intelligence, `sparta://event/{id}` opens "Decision on this phone". Back returns to the tab screen; the tapped notification disappears. Invalid links (unknown suffix, an id with characters other than A–Z a–z 0–9 `_` `-`, or longer than 64) are ignored: the app only comes to the foreground and does not crash. A link that arrives before onboarding is finished opens after it. | NOT RUN | Record: the `adb` commands with their `Status: ok` lines (call ids only) and a screenshot of each screen reached. |
| 8 | Live-call display updates | 1) Open Live call for a running simulated call (row 7).<br>2) Start `delivery-legit` (a few seconds of caller lines) and watch; repeat with another scenario from the Simulator Lab that raises risk.<br>3) Compare with the same call in the web app on the PC.<br>4) After the call ends read the summary card. | The banner goes "Connecting to the live feed" → "Live feed connected". The phase line changes in order ("Listening to the caller", "Sparta is speaking", …); transcript lines appear in order, an italic partial line is replaced by the final one; "Risk so far" updates; "Needs your decision" appears on escalation; "Simulated call: no real phone is ringing." and the "This is a simulated call. No real phone audio is involved…" banner are shown; nothing claims this phone is on the call audio ("This phone is not on the call audio."). At the end: "Call ended", a **Call summary** card and **View call details**. Content and order match the web app. | NOT RUN | Record: three screenshots (start, mid-call, end) with transcript text cropped; no screen recording with sound. |
| 9 | Recent-call history | 1) After rows 6–8 and 13 open **Calls** ("Recent calls").<br>2) Pull down, or tap **Refresh calls**.<br>3) Type part of a caller label in **Search calls**; try the chips (**Needs you**, **High risk**, …) and **Clear filters**.<br>4) Open one backend call and one "Decision on this phone" row.<br>5) Turn on airplane mode and reopen the tab. | Simulated backend calls and decisions made on this phone are in one list, newest first, with masked numbers (`+91 98•••• ••21` or "Private number"). Risk, language, category and attention filters hide the on-device decisions and the screen says so; search narrows the list. Offline the saved rows remain, with "Showing saved calls. Could not refresh: …". The backend calls match the web app's list. | NOT RUN | Record: a screenshot of the list (mask anything that looks like a number), one of the offline state. |
| 10 | Call-detail display | 1) Open a simulated backend call from Calls and scroll to the end; tap **Show translations**.<br>2) Open a "Decision on this phone" row.<br>3) Compare the simulated call with the web app's page for it. | Top to bottom: header (masked caller, status, "Simulated" badge), the audio note ("This is a simulated call. No real phone audio is involved…"), Summary (once the call has one), "Why Sparta thinks this", "What you can do", "Was this right?", Transcript, Timeline, "Your data", "Technical details". Risk level, category and summary equal the web app's. The on-device row is "Decision on this phone" (decision, reason, time, caller ID check, direction, decision time, sync) and says "Native call screening gives Sparta no audio and no words from the call, so this record has no transcript and no analysis." No raw number is shown anywhere. | NOT RUN | Record: screenshots of both screens (masked, transcript cropped). |
| 11 | Owner feedback is stored (the app has six feedback chips; **no thumbs and no free-text note**) | 1) Open a backend call → "Was this right?": tap one chip, e.g. **This was legitimate**.<br>2) Leave and reopen the call; swipe Sparta away and reopen the call.<br>3) On the PC read only the `feedback` list: `(Invoke-RestMethod "http://localhost:8000/api/v1/calls/$($call.id)").feedback` (use the id of the call you opened if it is another one).<br>4) Stop the backend and tap another chip. | "Thanks, your feedback was saved." and the chip reads "· Sent". After reopening (also after the process was killed) it still says Sent, because it is read back from the backend. The backend list contains exactly that kind (`correct_classification`, `was_spam`, `was_legitimate`, `wrong_language`, `poor_transcription` or `wrong_summary`) and no note; tapping a sent chip again sends nothing. With the backend down a failure message appears and the chip does not turn to Sent. | NOT RUN | Record: a screenshot of the Sent chip and the `feedback` list only (kind and time); never paste transcripts. |
| 12 | Take Over control availability matches the backend capability | For each case compare the phone with the backend's own answer: `(Invoke-RestMethod "http://localhost:8000/api/v1/calls/$($call.id)").capabilities` (`can_take_over`, `takeover_note`), and the call's `status`; use the id of the call you are looking at.<br>a) Active simulated call needing the owner (row 6): Call intelligence and Live call.<br>b) Tap **Take over (simulation)**, then look at the button again on both screens.<br>c) An ended call; and a phone-screened "Decision on this phone" row.<br>d) A backend whose provider reports `can_take_over: false`, or a real provider with no takeover number set in Assistant Studio. If you have none, mark d NOT RUN; do not fake it. | a) Enabled, labelled "Take over (simulation)", with "The backend says: Takeover is simulated: no real phone call is being bridged." (the backend's own wording). b) "Done in the simulator. No real call was affected."; afterwards disabled with "You already took over this call." (on the Live screen this is only unit-tested, `LiveCallViewModelTest`: confirm it). c) Ended: "This call is over, so live controls no longer apply."; the on-device row has no Take over control at all. d) Provider cannot transfer: disabled with "The active telephony provider cannot do this." plus "The backend says: `<takeover_note>`". **Rule:** enabled only if `capabilities.can_take_over` is true, the call is active, it is not a phone-screened call and not already taken over; the note is shown verbatim; nothing says a transfer happened unless the backend answered success. Known backend behaviour: a real provider with no usable takeover number reports `can_take_over: false` with a `takeover_note` ("Set the phone number Sparta should bridge you to (Assistant Studio) to enable Take Over."; a number without a country code gets a note asking for one), so the button is disabled with that note and a tap that is sent anyway is refused with 409 `unsupported_by_provider`: PASS is the note and no claim of a bridge. Real PSTN transfer is unverified in the backend itself. | NOT RUN | Record: per case a screenshot of the control and its reason line, and the printed `capabilities` object (no numbers). |
| 13 | An incoming real call is screened (allow, silence, reject) within the platform's 5 s deadline, and the app never claims it spoke to the caller | Needs rows 2 and 5a done (Block and Trust need the screening key the backend provides) and row 4a. From the second phone call this phone each time and hang up after about 15 s:<br>a) a number that is not a contact, not blocked and not trusted (the default policy *screens* unknown callers);<br>b) the same number after Calls → its "Decision on this phone" row → **Block this number**;<br>c) another number after **Trust this number**;<br>d) with caller ID hidden;<br>e) after restarting the phone, without opening Sparta, call once more.<br>Afterwards read Status → Last screening decision, the Calls tab and Diagnostics → Screening. | a) The ringer is silenced (the call stays visible) and a **Screening decisions** notification "Silenced a call from `<masked>`" appears; its expanded text ends "Sparta did not answer this call. It only changed how your phone handled it." b) The call is rejected (record what the caller hears), notification "Blocked a call from `<masked>`", and the call remains in Android's own call log by design. c) It rings normally, no notification, still recorded as allowed. d) Silenced as a hidden number ("Private number"). Every call has a "Decision on this phone" row with "Decided in N ms" far below 5 s (Sparta's own budget is 1.5 s, its watchdog 2.5 s), Diagnostics → "Deadline misses" stays 0, and e) is the slowest because the process starts cold. Sparta never answers, speaks, plays or records anything on these calls and shows no transcript or analysis for them. | NOT RUN | Record: screenshots of Status (last decision and time), the decision page and Diagnostics → Screening, numbers masked. **Never** a recording of a call. |
| 14 | Battery optimisation, Doze and background restrictions | 1) Settings → Apps → Sparta → Battery: note the setting, then set **Restricted** (and any maker-specific auto-start or background switch to its strictest).<br>2) Unplug and leave the locked phone untouched for 30+ minutes. Optional, to reach Doze sooner: `adb shell dumpsys battery unplug`, `adb shell dumpsys deviceidle force-idle`; undo with `adb shell dumpsys deviceidle unforce` and `adb shell dumpsys battery reset`.<br>3) While idle, call the phone (row 13a).<br>4) While idle, start a **new** `delivery-legit` call and see whether and when the notification comes (row 6 B).<br>5) Repeat with the battery setting on **Unrestricted**. | The phone call is still screened in every mode: a decision row with a latency far below 5 s, same ringer behaviour as row 13a (the system binds the screening service for each call). The notification while the app is closed may be late or missing under Doze, *Restricted* or a maker's battery manager, because WorkManager defers its sync by design: record what happened and how long it took. That is information about the platform, not a screening failure. | NOT RUN | Record: screenshots of the battery setting and of Status → Last screening decision; the notification delay in minutes. |
| 15 | Device rotation and process recreation | 1) With auto-rotate on, rotate to landscape and back on Status, Calls (text typed in **Search calls**), Call intelligence, Live call (call active), Privacy, an open confirmation dialog, and (on a fresh install) onboarding step 2 with an address typed.<br>2) Open Live call, press Home, run `adb shell am kill io.github.snowjug.sparta` (only kills a backgrounded app), reopen Sparta from Recents.<br>3) On Live call swipe Sparta away from Recents, then open it from the launcher.<br>4) Repeat 3 in the middle of onboarding. | 1) No crash and no flash back to a spinner: the same call is not re-fetched, typed search text and open dialogs survive, Live call stays connected or briefly reconnects. 2) Sparta reopens on the same Live call screen (Android restores the back stack), shows "Connecting to the live feed", then a fresh snapshot. 3) Sparta starts on **Status**, not onboarding; the backend address and the Calls history are still there and the role and permission state is re-read. 4) Onboarding restarts at Welcome with the default address, because the wizard state is not saved (anything already stored, such as the backend address, stays). Record any difference. | NOT RUN | Record: before and after screenshots for each case. |
| 16 | Network loss and recovery (airplane mode toggle) | **A, live:** with Live call open on an active simulated call, turn **Airplane mode** on, watch the banner for about a minute, turn it off, wait 30 s, then leave the screen and open it again.<br>**B, screens:** in airplane mode open Status → **Refresh status** and the Calls tab; turn it off and refresh both.<br>**C, voice but no data:** turn off Wi-Fi and mobile data (not airplane mode), call the phone from the second phone, then turn data back on and watch Diagnostics → "Events waiting to upload". | A: "Live feed lost. Reconnecting"; after about 30 s of failed retries (six attempts, pauses of 1, 2, 4, 8 and 15 s) "Live feed unavailable: The live connection was lost and could not be restored." By the code it does **not** reconnect by itself once it gave up; leaving the screen and returning (or Home and back after 5 s) reconnects with a fresh snapshot. Confirm or refute this. B: "Not reachable: The backend could not be reached. Showing the last known status." and saved calls with their note; refreshing after recovery clears both. C: the call is screened normally with no network (local data only) and recorded; "Events waiting to upload" rises by one and returns to 0 soon after the network is back (WorkManager waits for a connection and retries a failed attempt with a 30 s exponential backoff; the upload is idempotent, so the backend list shows no duplicate). Owner actions offline say "The backend could not be reached." and claim no success. | NOT RUN | Record: a screenshot of each banner, and Diagnostics → Sync before and after. |
| 17 | Background and foreground transitions | 1) Open Live call on an active call, press Home, wait 15 s, reopen from Recents.<br>2) Lock the screen for 30 s with Live call open, then unlock.<br>3) On Status leave for Settings → Apps → Sparta → Notifications, turn notifications off, return without restarting Sparta.<br>4) Open a notification with Sparta in the background, then with it swiped away.<br>5) While Sparta is in the background look for any persistent Sparta notification or foreground-service indicator. | 1–2) After about 5 s in the background the live connection is closed on purpose (nothing keeps the radio awake); on return the banner goes "Connecting to the live feed" → "Live feed connected" with a fresh snapshot, no crash, no duplicated transcript lines. 3) Status re-reads the permission and shows "Notifications are off". 4) As row 7. 5) There is none: Sparta has no foreground service and no wake lock of its own (§6). | NOT RUN | Record: screenshots of the banner sequence and of the re-read permission card. |
| 18 | Uninstall removes local data | 1) Before: `adb shell run-as io.github.snowjug.sparta ls databases files/datastore` (debug build; file names only) and note what the Calls tab shows.<br>2) `adb uninstall io.github.snowjug.sparta`.<br>3) `adb install -r app\build\outputs\apk\debug\app-debug.apk`, open Sparta and check onboarding, the Calls tab, Privacy → Backend, Settings → Default apps and the notification permission.<br>4) If device backup is on, restart the phone and check again. | Step 1 lists `sparta.db` (with `-wal` and `-shm`), WorkManager's `androidx.work.workdb` and `sparta_settings.preferences_pb`. After reinstall: onboarding starts from the beginning, the Calls tab says "No calls yet", no backend address is saved (the field only shows the debug default), Sparta no longer holds the screening role and, on Android 13+, the notification permission is asked for again. Backup and device transfer restore nothing (`allowBackup=false`; `data_extraction_rules.xml` excludes the root, file, database, sharedpref and external domains). The backend's copy of the history is untouched by an uninstall: delete it there (Privacy → Your data). | NOT RUN | Record: the `ls` listing before (file names only) and screenshots of onboarding and the empty Calls tab afterwards. |

**How to record results honestly.** A result stays `NOT RUN` until a person has run that check on a real phone. Then
replace it with PASS, FAIL or PARTIAL plus the date, device model, Android version and build (commit and APK SHA-256), and
write what you saw, not what the code intends; a surprise is a finding. Never commit real phone numbers, raw audio or
unredacted transcripts, and never keep screen recordings with sound, backend exports, tokens or full numbers: evidence
means masked screenshots and the masked, filtered `adb logcat` excerpts above, reviewed before they leave your machine.

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

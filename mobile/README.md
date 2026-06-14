# Tazkirati Mobile (iOS + Android)

Capacitor wrap of the web portal (`../frontend/`). No UI rewrite — the same
single-page app runs inside a native shell on both platforms. Run all commands
below from this `mobile/` directory.

## One-time setup

### Prereqs

- **Node 18+** and **npm**.
- **Xcode 15+** with Command Line Tools (`xcode-select --install`) for iOS builds.
- **Android Studio (Hedgehog/Iguana)** + Android SDK 34 + JDK 17 for Android builds.
- **CocoaPods** for iOS dependencies (`sudo gem install cocoapods` if not present).
- Apple Developer Program account ($99/yr) for TestFlight and App Store submission.
- Google Play Console account ($25 one-time) for Play Store submission.

### Install Capacitor + add platforms

```bash
npm install
npx cap add ios
npx cap add android
```

Both `ios/` and `android/` directories will be generated and should be committed
to git — that's the native project source that Xcode and Android Studio open.

## Point the app at your backend

Before the first build, open `../frontend/index.html` and update the constant:

```js
const TAZ_API_NATIVE_DEFAULT = 'https://tazkirati-web.onrender.com';
```

Set this to whatever URL your Render deployment is using. The web build is
unaffected — it always uses `location.origin`. This URL is only read inside the
Capacitor webview.

For staging swaps without a rebuild, you can also set `window.__TAZ_API__` at
runtime (e.g. from a deep link handler) — it takes precedence.

## Sync changes from the web

Every time you edit `../frontend/`, push the new web assets into both native
projects:

```bash
npx cap sync
```

## Open in IDEs

```bash
npx cap open ios       # opens Xcode
npx cap open android   # opens Android Studio
```

From there, the standard IDE workflows apply — Run on simulator/emulator,
attach a device, Archive for distribution.

## App icon and splash screen

Drop a `resources/icon.png` (1024×1024) and `resources/splash.png` (2732×2732)
into this directory, then generate per-platform assets:

```bash
npx capacitor-assets generate
```

Both files should keep the Tazkirati color palette (navy `#0F2A47` background,
paper `#F2EAD3` icon foreground).

## CORS

The backend already whitelists Capacitor webview origins
(`capacitor://localhost`, `https://localhost`, `http://localhost`,
`ionic://localhost`) automatically — no operator action needed unless you
override `CORS_ALLOWED_ORIGINS` to a strict list, in which case those four
schemes are still appended.

## Smoke test before requesting TestFlight / Play Internal Testing review

Run all of these on both an iOS simulator and an Android emulator, then repeat
on at least one real device per platform:

1. Cold install → splash → welcome → EN/AR toggle → kill + relaunch:
   language preference persists, RTL flip survives.
2. Customer login (`passenger@tazkirati.app`) → search Khartoum → Port Sudan
   → lock 2 seats → Generate Billing Reference → ticket modal with QR renders
   → My Tickets badge increments → kill app → relaunch → session restored,
   ticket still in list.
3. Provider login (`operator@tazkirati.app`) → My Trips tab → Add Trip with
   Weekly repeat → walk-in booking → Cash Confirm → ticket QR renders →
   manifest opens.
4. Background the booking screen for 60s → return → seat sync resumes, no
   crash, no duplicate request bursts in the Xcode/Android Studio network log.
5. Airplane-mode mid-search → connection-lost UX appears → restore → search
   retries; bad password → translated error toast in the active language.
6. Tail Render logs during smoke test to confirm the device is hitting the
   deployed backend rather than localhost.

## Hard prerequisites before store submission

These live outside the mobile codebase and are the project owner's call to
make:

- **Email OTP delivery must work.** Render free tier blocks outbound SMTP
  (`_send_email()` in `backend/src/auth/service.py`). Upgrade Render to Starter
  ($7/mo) to unblock SMTP, or swap `_send_email()` to a Resend HTTP API call
  on any plan. Without this, public users cannot register.
- **No more cold starts.** Render Starter removes the 15-min idle sleep and
  ~30s wake. The cold-start toast in the web app makes the wait visible but
  not gone; on a public app you'll want it gone before review.

## Deferred (post-launch follow-ups)

- Phone-OTP auth (AUTH-01, P-AUTH-01 in `Context/requirements.v2.md`) — Apple
  occasionally pushes back on email-only auth for travel apps; have an SMS
  gateway integration in your back pocket.
- Push notifications (SYS-05) — add `@capacitor/push-notifications` + FCM/APNs
  sender on the backend.
- WebSocket replacement for the long-poll seat sync — better battery life at
  scale on cellular.

# Native macOS menu-bar app

Requires macOS 14+. The app has a balance window and menu-bar remaining-data status. It refreshes every five minutes and after wake. Closing the balance window leaves the menu-bar app running; use its **Quit** button to stop it.

## Build and open

Install Apple's command-line tools (`xcode-select --install`) if needed. From the repository root:

```sh
bash desktop/macos/build.sh
open "build/macos/U Mobile Balance.app"
```

For both Apple silicon and Intel:

```sh
bash desktop/macos/build.sh --universal
```

The build script compiles the app, signs the local bundle ad hoc and runs mock API tests. It does not require Xcode project setup, a paid developer account or a signing certificate. This is a source build; no Apple-notarized distribution is supplied. Output and test results are under `build/macos/` and excluded from Git.

## Sign in

Enter your MyUMobile home-broadband email/password. If device approval is required, choose **Approve using MyUMobile on iPhone** and approve the computer in your primary phone's MyUMobile app. The computer polls normally and completes its own login.

**Send verification code instead** implements U Mobile's TAC alternative; a broadband SIM's messages may be available in its router. This alternative has mock contract coverage but has not been tested with a real TAC. Primary-phone approval is the live-tested path.

The main window and menu bar show the provider's quota. If several pools are returned, choose one with **Balance**. **Refresh** performs an immediate update.

## Storage and export

With **Keep me signed in using Keychain** enabled, tokens are stored in login Keychain. The service remains `local.hongvin.umobile-widget` for compatibility with the original app. Sign-out clears tokens and keeps the device UUID. Passwords, verification codes and temporary approval secrets are not saved.

The app writes `~/Library/Application Support/U Mobile Balance/status.json` with the latest quota and sanitized HTTP status/field shapes, permissions 0600. It contains personal usage information, but no credentials or raw account response. Another local widget can read its `balance.pools` entries, including `displayUsed`, `displayTotal`, `displayRemaining` and raw quantities. Timestamps use ISO 8601.

Real account sign-in, primary-phone approval and data retrieval were tested on Apple silicon. Universal compilation and API mocks also cover the Intel build; real Intel account login has not been separately tested.

# U Mobile Balance

[![Checks](https://github.com/hongvin/umobile-balance/actions/workflows/checks.yml/badge.svg)](https://github.com/hongvin/umobile-balance/actions/workflows/checks.yml)

Monitor U Mobile home-broadband data usage from a desktop or a small Wi-Fi display. Shows used, total and remaining data, with automatic refresh every five minutes.

| Version | Runs on | Setup |
| --- | --- | --- |
| Native menu-bar app | macOS 14+; Apple silicon or Intel build | [macOS guide](desktop/macos/README.md) |
| Floating desktop window and CLI | Windows, Linux, macOS; Python 3.11+ | [Desktop guide](docs/desktop.md) |
| Standalone display | Adafruit Feather ESP32-S3 TFT, CircuitPython 9.0.4 | [ESP32 guide](esp32/README.md) |

The ESP32 updates directly over Wi-Fi, even when your computer is asleep or switched off. Desktop clients refresh while running and awake. Each client signs in using its own device identity.

## Before you start

Use the email and password for your MyUMobile home-broadband account. Keep MyUMobile on your primary phone available to approve the new device. The tested service is U Home 5G; other U Mobile products and plans may have different balance formats.

This is an independent project using a private MyUMobile app API. It is not affiliated with or supported by U Mobile. Provider changes or device limits can require signing in again.

Use GitHub's **Code → Download ZIP**, or clone the source:

```sh
git clone https://github.com/hongvin/umobile-balance.git
cd umobile-balance
```

## Quick start: Windows

Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/), then download this repository or clone it. In PowerShell from the repository directory:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[remember]"
.\.venv\Scripts\python.exe -m umobile_balance
```

Enter your broadband credentials and approve the computer in MyUMobile. **Keep window on top** makes the balance useful as a desktop widget. **Keep me signed in** stores tokens in Windows Credential Locker; your account password is never saved.

## Quick start: Linux

Install Python 3.11+, venv support and Tkinter through your distribution. For Debian/Ubuntu, the relevant packages are `python3`, `python3-venv` and `python3-tk`. From the repository directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[remember]'
.venv/bin/python -m umobile_balance
```

Approve the computer in MyUMobile. Saved sessions require an unlocked Secret Service or KWallet credential store in your desktop session. You can leave **Keep me signed in** unchecked to keep tokens in memory only.

For a terminal reading, use `--cli`; use `--json` for integration with other desktop tools. First sign-in prompts for credentials and normal phone approval. See the [desktop guide](docs/desktop.md) for examples, startup instructions and troubleshooting.

## macOS

The native Swift app provides both a balance window and menu-bar status. With Apple's command-line developer tools installed:

```sh
bash desktop/macos/build.sh
open "build/macos/U Mobile Balance.app"
```

Use `--universal` to build for Apple silicon and Intel. The app saves its session in login Keychain when enabled. See [macOS instructions](desktop/macos/README.md). The Python desktop version also runs on macOS when your Python installation includes Tkinter.

## ESP32

Install CircuitPython 9.0.4 on an **Adafruit Feather ESP32-S3 TFT**. With its `CIRCUITPY` drive mounted:

```sh
python3 tools/install_esp32.py /Volumes/CIRCUITPY
```

On Windows use `py tools/install_esp32.py E:\` with your drive letter; Linux users pass their actual mount path. Existing Wi-Fi settings and saved login tokens are preserved. The installer replaces this project's firmware files; back up an existing board program first.

Edit `settings.toml` with your 2.4 GHz Wi-Fi credentials, safely eject and reset. Open the setup address on the display, enter its PIN, sign in and approve the ESP32 in MyUMobile. After setup it needs only power and Wi-Fi.

- Tap **BOOT/DFU** to refresh.
- Hold **BOOT/DFU** for three seconds to show setup address and PIN.
- **RESET** restarts the board and fetches the balance using its saved session.

The [ESP32 guide](esp32/README.md) covers first installation, upgrades and recovery. Other ESP32 boards need display and pin adaptations.

## Data and credentials

All provider requests use verified HTTPS. No proxy or custom certificate is needed. The password and temporary device-approval secret are never saved. Access and refresh tokens are credentials:

- Native macOS: login Keychain, with a device UUID retained after sign-out.
- Python: tokens stay in memory by default; optional native OS credential storage has no plaintext fallback. The disk identity file contains only a device UUID and the remember preference.
- ESP32: device UUID and tokens are stored in flash NVM, which is not encrypted storage. Local PIN-protected setup uses HTTP on your LAN; use it on a trusted network and keep port 8080 local.

The clients do not read the official app's private storage, remove other registered devices or change your primary device. The repository contains no account credentials, live tokens, Wi-Fi settings or personal balance captures. Please omit these from issues and pull requests.

MyUMobile reports byte quantities; data is divided by 2^30 and labeled GB to match its display. Missing or unfamiliar quotas produce an error rather than an invented zero. [API notes](docs/api.md) describe the recovered request contract and its limits.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
python3 -m umobile_balance --cli --demo
bash desktop/macos/build.sh --universal
```

`--demo` opens a clearly labeled desktop preview using sample data without account or network access. CI runs Python client, persistence, installer and GUI tests on Windows/Linux/macOS, plus a universal Swift build and mock API tests. Local tests skip GUI checks unless `RUN_GUI_TESTS=1` is set on a working desktop; CI requires them.

Real email login, primary-phone approval, token refresh and balance retrieval were tested with the macOS app and the Feather ESP32-S3 TFT. Windows/Linux carrier logins and native credential-store integration have not been tested with a real account; their UI and shared client behavior are covered by CI/mocks. The ESP32's physical button actions and display were developed on the stated board; no generic ESP32 compatibility is claimed.

Original code is MIT licensed. Bundled font, Adafruit library and brand-asset notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

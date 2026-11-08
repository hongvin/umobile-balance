# Windows, Linux and Python desktop

The Python version is a floating balance window with an optional always-on-top setting, plus a CLI. Requires Python 3.11+. The GUI uses Tkinter; `python -m tkinter` should open its test window ([Python documentation](https://docs.python.org/3/library/tkinter.html)). On Linux, install your distribution's Python Tk package if needed.

## Install

Clone or download this repository. Create a virtual environment and install the package from the repository directory.

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install ".[remember]"
.\.venv\Scripts\python.exe -m umobile_balance
```

Linux/macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install '.[remember]'
.venv/bin/python -m umobile_balance
```

To use memory-only sessions without the optional credential-store dependency, install `.` instead of `.[remember]` and leave **Keep me signed in** unchecked.

## Sign in and use

1. Enter your MyUMobile broadband email and password.
2. Click **Sign in**. If requested, open MyUMobile on your existing primary phone and approve this computer. Approval is checked every ten seconds, until approved or expired.
3. The window shows remaining GB, used GB, total allowance and expiry. **Refresh** requests a new reading; automatic refresh runs every five minutes.
4. Enable **Keep window on top** for a small desktop display. Closing the window stops automatic updates; an in-flight HTTPS request may finish before the process exits.
5. **Sign out** removes saved tokens for this Python client and preserves its device UUID.

The Python app uses the main returned DATA/PLAN balance. The native macOS app additionally offers a picker for multiple returned pools. The Python app uses normal primary-phone approval; the native macOS app also implements a TAC alternative.

## Saved login

The optional `keyring` extra uses native [credential-store backends](https://keyring.readthedocs.io/en/latest/): Windows Credential Locker, macOS Keychain, Secret Service or KWallet. Plaintext and third-party file backends are not accepted. Linux needs a running, unlocked desktop credential service; a headless SSH session may not have one. An unavailable/locked store produces an error, not a plaintext fallback.

The credential service is `io.github.hongvin.umobile-balance`, account `session-v1`. The identity file contains only UUID/preferences:

| OS | Identity file |
| --- | --- |
| Windows | `%LOCALAPPDATA%\U Mobile Balance\identity.json` |
| Linux | `${XDG_STATE_HOME:-~/.local/state}/umobile-balance/identity.json` |
| macOS | `~/Library/Application Support/U Mobile Balance Python/identity.json` |

Without a saved login, restarting requires sign-in/approval again using the same UUID. Avoid deleting the identity file unnecessarily; each new UUID may count toward U Mobile's registered-device limit.

## CLI and other widgets

Using your virtual environment's Python:

```sh
python -m umobile_balance --cli --remember
python -m umobile_balance --json
python -m umobile_balance --sign-out
python -m umobile_balance --cli --demo
```

`--remember` requires the optional extra and an unlocked native credential store. `--json` prints one normalized balance object to stdout; prompts/status go to stderr and the password is entered with `getpass`. It contains plan/usage information, not tokens. After initial sign-in, another desktop tool can run it every 300 seconds. Keep the OS credential store unlocked and avoid running several clients that refresh the same saved Python session concurrently.

For example, a Conky text item can run `/absolute/path/to/.venv/bin/umobile-balance --cli` with a 300-second refresh interval. Windows tools can invoke `.venv\Scripts\python.exe -m umobile_balance --json` and parse the JSON. These integrations require their own display configuration; this repository supplies the window and command.

For launch-at-login, create a Windows Startup shortcut or a Linux desktop autostart entry pointing to the virtual environment's interpreter and `-m umobile_balance`. Use absolute paths. Account passwords do not belong in shortcut arguments or startup files.

## Troubleshooting

- **Tkinter missing:** run `python -m tkinter`; install your distribution's Tk support or use `--cli`.
- **Credential store unavailable:** unlock/configure the native store, or use a memory-only session.
- **Approval expires/device limit:** sign in again or manage registered devices in MyUMobile. No client removes devices automatically.
- **HTTP 401 after refresh:** the saved session may have been revoked. Sign out and sign in again.
- **Network failure:** the window retains its last successful reading and reports the failed refresh. Check its update message before relying on the number.

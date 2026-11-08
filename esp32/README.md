# Standalone ESP32 display

Tested hardware: **Adafruit Feather ESP32-S3 TFT**, 240 × 135 display, running **CircuitPython 9.0.4**. This is the built-in TFT Feather; other ESP32 displays require adapting the display and button code. [Official board downloads](https://circuitpython.org/board/adafruit_feather_esp32s3_tft/) provide firmware and previous versions.

## First installation

1. Install CircuitPython 9.0.4 for this exact board using Adafruit's normal board setup process. Its USB drive should appear as `CIRCUITPY`. Back up an existing `code.py` before replacing it.
2. Install this repository's firmware from its root directory:

   ```sh
   python3 tools/install_esp32.py /Volumes/CIRCUITPY
   ```

   Windows: `py tools/install_esp32.py E:\` using your drive letter. Linux: use the mount path shown by your file manager, such as `/media/yourname/CIRCUITPY`. `--dry-run` lists the operation without writing.

3. Edit `settings.toml` on the board with your 2.4 GHz Wi-Fi name/password. The installer creates a template only if that file is absent; upgrades preserve existing settings. Keep the quotes, and escape embedded quotes/backslashes using TOML syntax.
4. Safely eject the USB drive, then press RESET. Allow time for Wi-Fi and network-time setup.
5. Open the address shown on the display from a browser on the same LAN. Enter the six-digit PIN on the display, then your MyUMobile broadband credentials.
6. Approve the ESP32 in MyUMobile on your primary phone. The display fetches usage and starts five-minute updates. Its tokens and device UUID persist across restarts.

For setup again, hold BOOT/DFU for three seconds. The current firmware shows the setup screen for 30 seconds; the PIN remains valid until restart. The browser form may still be used after the usage screen returns.

## Daily use

The screen shows used GB, total allowance, remaining GB and Malaysia update time. Short press BOOT/DFU to refresh. Hold it for three seconds to show setup. The other onboard button is hardware RESET; it restarts the device and reloads the balance.

After setup, use a USB power adapter or suitable battery. The Mac and desktop apps are not involved in updates. A failed request retains the last reading; it is marked stale after 11 minutes. Device approval still requires the primary phone when a fresh login is needed.

## Upgrade and recovery

Rerun the installer and reset. It copies the shared `umobile_balance/core.py` to the board as `umobile_core.py`, then the ESP32 controller, portal, renderer, fonts and pinned libraries. It does not erase flash, NVM tokens, Wi-Fi settings or unrelated files. `code.py` is written last; safely eject/reset after copying so the firmware reads complete files.

The source libraries include Display Text 3.1.0, matching the working board's library version. Source pins/hashes and licenses are included. The bundled libraries target the tested CircuitPython 9 setup; newer CircuitPython versions have not been hardware-verified.

If the board does not start, connect its serial console and check the exception. Confirm the exact board, CircuitPython version and complete `lib/`, `fonts/` and `assets/` folders. If an import appears empty after copying, safely eject and reset before retrying. To restore your prior program, copy your own backup `code.py` back; the installer never formats the board.

## Local data

Wi-Fi is in `settings.toml`. U Mobile tokens and UUID are in ESP32 flash NVM with a corruption checksum, not encryption. Sign-out on the setup page clears tokens while retaining the UUID. The PIN/CSRF-protected setup page uses HTTP on the LAN; outbound U Mobile requests use standard verified HTTPS. Keep the setup page on a trusted local network.

The installer does not enable CircuitPython's web workflow. A Wi-Fi settings file can bring up a CircuitPython web service if the user separately enables it; this project only starts its own setup server on port 8080.

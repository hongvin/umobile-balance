#!/usr/bin/env python3
"""Copy only this project's firmware; never overwrite existing Wi-Fi settings."""
import argparse
import os
from pathlib import Path
import shutil


def install(destination, dry_run=False):
    root = Path(__file__).resolve().parents[1]
    destination = Path(destination).resolve()
    if not (destination / "boot_out.txt").is_file():
        raise ValueError("Choose the mounted CIRCUITPY drive containing boot_out.txt")
    board = (destination / "boot_out.txt").read_text(errors="replace")
    if "Feather ESP32" not in board or "TFT" not in board:
        raise ValueError("This firmware is for the Adafruit Feather ESP32-S3 TFT; check your board model")
    pairs = [(root / "umobile_balance/core.py", destination / "umobile_core.py")]
    firmware = root / "esp32"
    for name in ("portal.py", "screen.py", "assets", "fonts", "lib"):
        source = firmware / name
        sources = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file())
        for file in sources:
            if "__pycache__" not in file.parts and file.suffix != ".pyc":
                pairs.append((file, destination / file.relative_to(firmware)))
    # Write the entrypoint last. Only source/data files above are replaced.
    pairs.append((firmware / "code.py", destination / "code.py"))
    for source, target in pairs:
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as file:
                file.write(source.read_bytes()); file.flush(); os.fsync(file.fileno())
    if not dry_run and not (destination / "settings.toml").exists():
        shutil.copyfile(firmware / "settings.toml.example", destination / "settings.toml")
    print(("Would copy" if dry_run else "Copied"), len(pairs), "files to", destination)
    print("Existing settings.toml and saved NVM tokens are preserved. Safely eject and reset after copying.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("drive", help="CIRCUITPY mount path, for example E:\\ or /Volumes/CIRCUITPY")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try: install(args.drive, args.dry_run)
    except (OSError, ValueError) as error: parser.exit(1, str(error) + "\n")


if __name__ == "__main__": main()

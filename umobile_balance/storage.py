"""Only the device UUID/preferences go to disk. Tokens use an OS credential store."""
import json
import os
from pathlib import Path
import platform
import tempfile

from .core import uuid

SERVICE = "io.github.hongvin.umobile-balance"
ACCOUNT = "session-v1"
SESSION_KEYS = ("deviceId", "accessToken", "refreshToken", "expiresAt")
NATIVE_BACKENDS = ("keyring.backends.macOS", "keyring.backends.Windows",
                   "keyring.backends.SecretService", "keyring.backends.kwallet",
                   "keyring.backends.libsecret")


def state_directory():
    if platform.system() == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "U Mobile Balance"
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/U Mobile Balance Python"
    return Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "umobile-balance"


def native_backend():
    try:
        import keyring
        selected = keyring.get_keyring()
        candidates = getattr(selected, "backends", [selected])
        for backend in candidates:
            if type(backend).__module__ in NATIVE_BACKENDS and backend.priority > 0:
                return backend
    except Exception:
        pass
    raise RuntimeError("An unlocked OS credential store is required. Install the 'remember' extra, or leave Keep me signed in unchecked.")


class SessionStore:
    def __init__(self, directory=None, backend=None):
        self.directory = Path(directory) if directory is not None else state_directory()
        self.path = self.directory / "identity.json"
        self.backend = backend
        self.load_error = ""
        self.had_saved_session = False
        config = json.loads(self.path.read_text("utf-8")) if self.path.exists() else {}
        self.state = {"deviceId": config.get("deviceId") or uuid()}
        self.remember = config.get("remember") is True
        if self.remember:
            self.had_saved_session = True
            try:
                value = self._backend().get_password(SERVICE, ACCOUNT)
                saved = json.loads(value) if value else {}
                if saved.get("deviceId") == self.state["deviceId"]:
                    self.state.update({key: saved[key] for key in SESSION_KEYS if key in saved})
            except Exception:
                self.load_error = "Saved login could not be opened. Unlock your OS credential store, then restart or sign in again."
        if not self.path.exists():
            self._write_identity()

    def _backend(self):
        if self.backend is None:
            self.backend = native_backend()
        return self.backend

    def _write_identity(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        # This file contains no password, bearer token, or approval secret.
        value = {"deviceId": self.state["deviceId"], "remember": self.remember}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.directory, delete=False) as file:
            temporary = Path(file.name)
            try:
                json.dump(value, file); file.flush(); os.fsync(file.fileno())
            except Exception:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def save(self):
        has_session = bool(self.state.get("accessToken") and self.state.get("refreshToken"))
        if self.remember:
            self._backend()  # Fail before login if secure storage is unavailable.
        if self.remember and has_session:
            saved = {key: self.state[key] for key in SESSION_KEYS if key in self.state}
            self._backend().set_password(SERVICE, ACCOUNT, json.dumps(saved))
            self.had_saved_session = True
        elif self.had_saved_session:
            backend = self._backend()
            if backend.get_password(SERVICE, ACCOUNT) is not None:
                backend.delete_password(SERVICE, ACCOUNT)
            self.had_saved_session = False
        self._write_identity()

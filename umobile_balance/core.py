"""U Mobile's recovered request contract, shared by hardware and desktop tests."""
import os
import json
import time
import binascii
import math

BASE = "https://api-myumobileapp.u.com.my/mobile"
PATHS = (
    "/auth/v1/auth/login/email", "/auth/v1/auth/refresh", "/user/v1/balance",
    "/auth/v1/device/request-confirm", "/auth/v1/device/poll-result", "/auth/v1/device/complete",
)


def random_hex(size=16):
    return binascii.hexlify(os.urandom(size)).decode("ascii")


def uuid():
    value = random_hex().upper()
    return "-".join((value[:8], value[8:12], value[12:16], value[16:20], value[20:]))


def checksum(payload):
    # Corruption detection only; tokens are stored in the device's flash, not encrypted by this checksum.
    value = 2166136261
    for byte in payload:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value.to_bytes(4, "big") + len(payload).to_bytes(4, "big")


class StateStore:
    """Checksummed NVM record. Passwords and approval secrets never enter this store."""
    def __init__(self, nvm):
        self.nvm = nvm
        self.state = {}
        raw = bytes(nvm[:])
        if raw[:4] == b"UMB1":
            size = int.from_bytes(raw[4:6], "big")
            payload = raw[14:14 + size]
            if size <= len(raw) - 14 and checksum(payload) == raw[6:14]:
                try:
                    self.state = json.loads(payload.decode("utf-8"))
                except (ValueError, UnicodeError):
                    pass
        if "deviceId" not in self.state:
            self.state = {"deviceId": uuid()}
            self.save()

    def save(self):
        payload = json.dumps(self.state).encode("utf-8")
        if len(payload) > len(self.nvm) - 14:
            raise RuntimeError("Session exceeds device NVM capacity")
        packet = b"UMB1" + len(payload).to_bytes(2, "big") + checksum(payload) + payload
        self.nvm[:] = packet + bytes(len(self.nvm) - len(packet))


class APIError(Exception):
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        self.code = payload.get("errorCode", "REQUEST_FAILED")
        if not isinstance(self.code, str):
            self.code = "REQUEST_FAILED"
        super().__init__("HTTP %d: %s" % (status, self.code))


def unwrap(payload):
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def parse_balance(payload):
    data = unwrap(payload)
    rows = data.get("balances", [])
    candidates = [row for row in rows if str(row.get("type", "")).upper() == "DATA"]
    if not candidates:
        raise RuntimeError("No data quota in server response")
    # CircuitPython 9's next() accepts one argument and has no default-value parameter.
    row = candidates[0]
    for candidate in candidates:
        if candidate.get("category") == "PLAN":
            row = candidate
            break
    values = [float(row[key]) for key in ("consumed", "originalBalance", "balance")]
    if any(not math.isfinite(v) or v < 0 for v in values) or values[1] <= 0:
        raise RuntimeError("Unrecognized quota values")
    return {
        "plan": data.get("planName", "U Mobile"),
        "name": row.get("name", "Home broadband"),
        "usedGB": values[0] / 1073741824,
        "totalGB": values[1] / 1073741824,
        "remainingGB": values[2] / 1073741824,
        "expiry": row.get("expirationDate", ""),
        "updatedAt": time.time(),
    }


class Client:
    def __init__(self, store, transport):
        self.store = store
        self.transport = transport
        self.approval = None
        self.snapshot = None
        self.last_http = None
        self.last_path = None

    @property
    def signed_in(self):
        return bool(self.store.state.get("accessToken") and self.store.state.get("refreshToken"))

    @property
    def device_id(self):
        return self.store.state["deviceId"]

    @staticmethod
    def device_info():
        return {"platform": "IOS", "osVersion": "CircuitPython 9.0.4", "appVersion": "4.0.2",
                "manufacturer": "Adafruit", "model": "Feather ESP32-S3 TFT"}

    def request(self, path, method="POST", body=None, bearer=None):
        if path not in PATHS:
            raise ValueError("Unrecognized API path")
        headers = {"Accept": "application/json", "Accept-Language": "en", "Connection": "close"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        status, payload = self.transport(method, BASE + path, body, headers)
        self.last_http, self.last_path = status, path
        print("API", method, path, status)  # Status only: no bodies, credentials, or tokens.
        reported = payload.get("statusCode", status)
        if not isinstance(reported, int):
            reported = status
        if not 200 <= status < 300 or reported >= 400:
            raise APIError(max(status, reported), payload)
        return payload

    def accept_tokens(self, result, old_refresh=None):
        data = unwrap(result)
        access = data.get("accessToken")
        refresh = data.get("refreshToken") or old_refresh
        if not access or not refresh:
            raise RuntimeError("Approval returned no login tokens; manage devices in MyUMobile if the limit was reached")
        updated = dict(self.store.state)
        updated["accessToken"], updated["refreshToken"] = access, refresh
        try:
            seconds = int(data.get("expiresIn") or 0)
        except (ValueError, TypeError):
            seconds = 0
        updated["expiresAt"] = time.time() + seconds if seconds > 0 else 0
        previous = self.store.state
        self.store.state = updated
        try:
            self.store.save()
        except Exception:
            self.store.state = previous
            raise
        self.approval = None

    def login(self, email, password):
        body = {"email": email.strip(), "password": password, "deviceId": self.device_id, "deviceInfo": self.device_info()}
        try:
            result = self.request("/auth/v1/auth/login/email", body=body)
        except APIError as error:
            data = unwrap(error.payload)
            if error.code == "LOGIN_BIND_DEVICE_VERIFY" and data.get("secretToken"):
                self.approval = {"secret": data["secretToken"],
                    "expires": time.monotonic() + float(data.get("expiresIn") or 180)}
                return False
            raise
        self.accept_tokens(result)
        return True

    def request_primary(self):
        pending = self.approval
        if not pending or pending["expires"] < time.monotonic():
            raise RuntimeError("Device verification expired. Sign in again.")
        body = self.device_info()
        body["deviceId"], body["type"] = self.device_id, "PRIMARY"
        result = unwrap(self.request("/auth/v1/device/request-confirm", body=body, bearer=pending["secret"]))
        if not result.get("sessionId"):
            raise RuntimeError("Approval response has no session ID")
        pending["sessionId"] = result["sessionId"]
        seconds = float(result.get("expiresIn") or 180)
        pending["expires"] = min(pending["expires"], time.monotonic() + max(seconds, 1))

    def poll_approval(self):
        pending = self.approval
        if not pending or not pending.get("sessionId"):
            return False
        if pending["expires"] < time.monotonic():
            self.approval = None
            raise RuntimeError("Approval expired. Sign in again.")
        body = {"deviceId": self.device_id, "sessionId": pending["sessionId"]}
        result = unwrap(self.request("/auth/v1/device/poll-result", body=body, bearer=pending["secret"]))
        if result.get("approved") is True:
            completed = self.request("/auth/v1/device/complete", body=body, bearer=pending["secret"])
            self.accept_tokens(completed)
            return True
        if result.get("pending") is not True:
            self.approval = None
            raise RuntimeError("Device approval was declined")
        return False

    def refresh(self):
        previous = self.store.state["refreshToken"]
        try:
            result = self.request("/auth/v1/auth/refresh", body={"refreshToken": previous})
        except APIError as error:
            if error.status in (401, 403):
                self.sign_out()
            raise
        self.accept_tokens(result, previous)

    def balance(self):
        if not self.signed_in:
            raise RuntimeError("Sign in to U Mobile")
        refreshed = False
        expires = self.store.state.get("expiresAt", 0)
        if expires and expires - time.time() < 45:
            self.refresh()
            refreshed = True
        try:
            result = self.request("/user/v1/balance", method="GET", bearer=self.store.state["accessToken"])
        except APIError as error:
            if error.status != 401 or refreshed:
                raise
            self.refresh()
            result = self.request("/user/v1/balance", method="GET", bearer=self.store.state["accessToken"])
        self.snapshot = parse_balance(result)
        return self.snapshot

    def sign_out(self):
        self.store.state = {"deviceId": self.device_id}
        self.store.save()
        self.approval = None
        self.snapshot = None

"""Standalone U Mobile usage display for Adafruit Feather ESP32-S3 TFT / CircuitPython 9."""
import os
import gc
import time
import ssl
import rtc
import board
import wifi
import socketpool
import microcontroller
import digitalio
import supervisor
import adafruit_requests
import adafruit_ntp
from umobile_core import Client, StateStore
from portal import Portal
from screen import Screen

class App:
    def __init__(self):
        self.screen = Screen()
        self.message = "Sign in with your MyUMobile broadband email and password."
        self.store = StateStore(microcontroller.nvm)
        self.pool = None
        self.http = None
        self.portal = None
        self.pin = str(100000 + int.from_bytes(os.urandom(4), "big") % 900000)
        self.client = Client(self.store, self.transport)
        self.next_refresh = 0
        self.next_poll = 0
        self.setup_until = 0
        self.last_success = None
        self.last_wifi_retry = -60
        self.last_draw = 0
        self.button = digitalio.DigitalInOut(board.BUTTON)
        self.button.switch_to_input(pull=digitalio.Pull.UP)
        self.pressed_at = None
        self.long_press = False

    def transport(self, method, url, body, headers):
        gc.collect()
        with self.http.request(method, url, json=body, headers=headers, timeout=20, allow_redirects=False) as response:
            status = response.status_code
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("The API returned an unfamiliar response")
        return status, payload

    def connect(self):
        if not wifi.radio.connected:
            self.screen.setup_page("Connecting Wi-Fi", footer="Using saved Wi-Fi settings")
            ssid, password = os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD")
            if not ssid:
                raise RuntimeError("Set Wi-Fi in settings.toml")
            wifi.radio.connect(ssid, password, timeout=15)
        if self.pool is None:
            self.pool = socketpool.SocketPool(wifi.radio)
            self.screen.setup_page("Setting clock", footer="Checking network time")
            try:
                rtc.RTC().datetime = adafruit_ntp.NTP(self.pool, socket_timeout=2).datetime
            except (OSError, RuntimeError):
                print("CLOCK NTP unavailable; keeping RTC")
            context = ssl.create_default_context()
            self.http = adafruit_requests.Session(self.pool, context)
            self.portal = Portal(self.pool, self, self.pin)
        print("NETWORK", wifi.radio.ipv4_address, "PORT", 8080)
        self.draw()

    def draw(self):
        if self.client.snapshot and time.monotonic() >= self.setup_until:
            stale = self.last_success is not None and time.monotonic() - self.last_success > 660
            self.screen.balance(self.client.snapshot, stale)
        else:
            address = "%s:8080" % wifi.radio.ipv4_address if wifi.radio.connected else "Wi-Fi disconnected"
            heading = "Approve on iPhone" if self.client.approval else ("Loading balance" if self.client.signed_in else "One-time setup")
            footer = "Open MyUMobile to approve" if self.client.approval else "Open address in browser"
            self.screen.setup_page(heading, address, self.pin, footer)

    def login(self, email, password):
        try:
            if not email or not password:
                raise RuntimeError("Enter your email and password")
            if self.client.login(email, password):
                self.refresh_balance()
            else:
                self.client.request_primary()
                self.next_poll = time.monotonic() + 10
                self.message = "Approval requested. Open MyUMobile on your iPhone and approve the ESP32."
        except Exception as error:
            self.message = str(error)
            print("LOGIN", type(error).__name__)
        self.draw()

    def refresh_balance(self):
        self.next_refresh = time.monotonic() + 300
        try:
            self.client.balance()
            self.last_success = time.monotonic()
            self.message = "Updated directly from U Mobile."
            print("BALANCE_OK", "%.2f" % self.client.snapshot["usedGB"], "%.2f" % self.client.snapshot["totalGB"])
        except Exception as error:
            self.message = str(error)
            self.next_refresh = time.monotonic() + 60
            print("BALANCE_FAILED", type(error).__name__)
        self.draw()

    def status(self):
        return {"signedIn": self.client.signed_in, "approvalPending": self.client.approval is not None,
                "balance": self.client.snapshot, "message": self.message,
                "lastHTTP": self.client.last_http, "lastPath": self.client.last_path,
                "refreshSeconds": 300, "standalone": True, "ip": str(wifi.radio.ipv4_address)}

    def run(self):
        while True:
            now = time.monotonic()
            try:
                if not wifi.radio.connected or self.portal is None:
                    if now - self.last_wifi_retry > 20:
                        self.last_wifi_retry = now
                        self.connect()
                if wifi.radio.connected and self.portal is not None:
                    self.portal.handle()
                    if self.client.approval and self.client.approval.get("sessionId") and now >= self.next_poll:
                        self.next_poll = now + 10
                        try:
                            if self.client.poll_approval():
                                self.message = "Device approved."
                                self.refresh_balance()
                        except Exception as error:
                            self.message = str(error)
                            print("APPROVAL_CHECK", type(error).__name__)
                        self.draw()
                    if self.client.signed_in and not self.client.approval and now >= self.next_refresh:
                        self.refresh_balance()
                pressed = not self.button.value
                if pressed and self.pressed_at is None:
                    self.pressed_at = now; self.long_press = False
                elif pressed and not self.long_press and now - self.pressed_at >= 3:
                    self.long_press = True; self.setup_until = now + 30; self.draw()
                elif not pressed and self.pressed_at is not None:
                    if not self.long_press and self.client.signed_in:
                        self.next_refresh = 0
                    self.pressed_at = None
                if self.client.snapshot and self.display_needs_redraw(now):
                    self.draw()
                if now - self.last_draw >= 30:
                    self.last_draw = now
                    self.draw()
            except Exception as error:
                self.message = str(error)
                print("LOOP", type(error).__name__)
                self.draw()
                time.sleep(1)
            time.sleep(.05)

    def display_needs_redraw(self, now):
        if self.setup_until and now >= self.setup_until:
            self.setup_until = 0; return True
        return False


supervisor.runtime.autoreload = True
app = App()
app.run()

"""PIN-protected local setup portal. Never returns credentials or session tokens."""
import json
import time
try:
    from umobile_core import random_hex
except ImportError:
    from umobile_balance.core import random_hex


def escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def unquote(value):
    value = value.replace("+", " ")
    out = bytearray()
    i = 0
    while i < len(value):
        if value[i] == "%":
            if i + 2 >= len(value):
                raise ValueError("Invalid form encoding")
            out.append(int(value[i + 1:i + 3], 16)); i += 3
        else:
            out.extend(value[i].encode("utf-8")); i += 1
    return out.decode("utf-8")


def parse_form(body):
    form = {}
    for pair in body.decode("utf-8").split("&"):
        if "=" in pair:
            key, value = pair.split("=", 1)
            form[unquote(key)] = unquote(value)
    return form


STYLE = """<style>
*{box-sizing:border-box}body{margin:0;background:#f5f4f0;color:#13222d;font:16px/1.5 system-ui,sans-serif}
main{max-width:520px;margin:8vh auto;padding:32px;background:white;border:1px solid #deded6;border-radius:20px}
.eyebrow{font-size:12px;letter-spacing:.12em;color:#d85519;font-weight:700}h1{font-size:30px;line-height:1.2;margin:12px 0 20px}
p{color:#52606a}label{display:block;margin-top:18px;font-size:14px}input{display:block;width:100%;font:inherit;padding:12px;border:1px solid #bdc6cb;border-radius:8px;margin:6px 0}
button{font:inherit;font-weight:600;border:0;border-radius:8px;padding:13px 18px;background:#e26321;color:white;cursor:pointer;margin-top:20px}
.muted{font-size:13px;color:#68747d}.number{font-size:44px;font-weight:700;letter-spacing:-.04em}.secondary{background:#e9edef;color:#253842;margin-right:8px}
@media(max-width:560px){main{margin:20px 12px;padding:24px}}
</style>"""


class Portal:
    def __init__(self, pool, app, pin):
        self.app = app
        self.pin = pin
        self.csrf = random_hex()
        self.cookie = random_hex()
        self.failures = 0
        self.blocked_until = 0
        self.socket = pool.socket(pool.AF_INET, pool.SOCK_STREAM)
        self.socket.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
        self.socket.bind(("0.0.0.0", 8080))
        self.socket.listen(2)
        self.socket.settimeout(0)

    def page(self, authorized):
        app = self.app
        token = '<input type="hidden" name="csrf" value="%s">' % self.csrf
        refresh = '<meta http-equiv="refresh" content="10">' if authorized and (app.client.signed_in or app.client.approval) else ""
        html = '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>U Mobile Display</title>%s%s</head><body><main><div class="eyebrow">ESP32 / U MOBILE</div>' % (STYLE, refresh)
        if not authorized:
            html += '<h1>Connect to your display</h1><p>Enter the six-digit setup PIN shown on the ESP32 screen.</p><form method="post" action="/unlock">%s<label>Display PIN<input name="pin" inputmode="numeric" pattern="[0-9]{6}" maxlength="6" required autofocus autocomplete="off"></label><button>Continue</button></form>' % token
        elif app.client.signed_in:
            balance = app.client.snapshot
            html += '<h1>Home broadband usage</h1>'
            if balance:
                html += '<div class="number">%.2f GB</div><p>used of %.2f GB<br><strong>%.2f GB remaining</strong></p>' % (balance["usedGB"], balance["totalGB"], balance["remainingGB"])
            html += '<p>%s</p><form method="post" action="/refresh">%s<button>Refresh balance</button></form>' % (escape(app.message), token)
            html += '<p class="muted">The ESP32 talks directly to U Mobile over Wi-Fi. Your Mac can be switched off.</p>'
            html += '<form method="post" action="/signout">%s<button class="secondary">Sign out this display</button></form>' % token
        elif app.client.approval:
            html += '<h1>Approve on your iPhone</h1><p>Open MyUMobile on your primary device and approve <strong>Feather ESP32-S3 TFT</strong>.</p><p>%s</p><p class="muted">This page checks automatically. Keep the ESP32 powered on.</p>' % escape(app.message)
        else:
            html += '<h1>Sign in to U Mobile</h1><p>%s</p><form method="post" action="/login">%s<label>Broadband email<input name="email" type="email" autocomplete="username" required></label><label>Password<input name="password" type="password" autocomplete="off" required></label><button>Sign in and request iPhone approval</button></form><p class="muted">The password is sent to U Mobile over HTTPS and is never saved. Session tokens are kept in this ESP32’s flash memory.</p>' % (escape(app.message), token)
        return html + '<p class="muted">Standalone Wi-Fi display · refreshes every 5 minutes</p></main></body></html>'

    def handle(self):
        try:
            conn, _ = self.socket.accept()
        except OSError:
            return
        try:
            conn.settimeout(2)
            request = bytearray(); buf = bytearray(1024)
            while b"\r\n\r\n" not in request:
                size = conn.recv_into(buf)
                if not size:
                    return
                request.extend(memoryview(buf)[:size])
                if len(request) > 8192:
                    return
            header, body = bytes(request).split(b"\r\n\r\n", 1)
            lines = header.decode("utf-8").split("\r\n")
            method, path, _ = lines[0].split(" ")
            headers = {}
            for line in lines[1:]:
                key, value = line.split(":", 1); headers[key.lower()] = value.strip()
            length = int(headers.get("content-length", "0"))
            if length > 4096 or length < 0:
                return
            while len(body) < length:
                size = conn.recv_into(buf)
                if not size:
                    return
                body += bytes(memoryview(buf)[:size])
            authorized = ("umb=" + self.cookie) in headers.get("cookie", "").split("; ")
            form = parse_form(body[:length]) if method == "POST" else {}
            status = "200 OK"; extra = ""; content_type = "text/html; charset=utf-8"
            if method == "POST":
                origin = headers.get("origin")
                if origin and origin != "http://" + headers.get("host", ""):
                    self.respond(conn, "403 Forbidden", "Origin rejected"); return
                if form.get("csrf") != self.csrf:
                    self.respond(conn, "403 Forbidden", "Reload the setup page"); return
                if path == "/unlock":
                    if time.monotonic() < self.blocked_until or form.get("pin") != self.pin:
                        self.failures += 1
                        if self.failures >= 5:
                            self.blocked_until = time.monotonic() + 30
                        self.respond(conn, "403 Forbidden", "Check the PIN on the display, then return to the setup page."); return
                    authorized = True; self.failures = 0
                    extra = "Set-Cookie: umb=%s; HttpOnly; SameSite=Strict; Path=/\r\n" % self.cookie
                elif not authorized:
                    self.respond(conn, "403 Forbidden", "Unlock using the display PIN first"); return
                elif path == "/login":
                    self.app.login(form.get("email", ""), form.get("password", ""))
                    form.clear(); body = b""; request = None
                elif path == "/refresh":
                    self.app.refresh_balance()
                elif path == "/signout":
                    self.app.client.sign_out(); self.app.message = "Signed out. Sign in again to resume updates."
                    self.app.draw()
                else:
                    self.respond(conn, "404 Not Found", "Unknown action"); return
                self.respond(conn, "303 See Other", "Continue", extra + "Location: /\r\n"); return
            if path == "/status" and authorized:
                payload = json.dumps(self.app.status()); content_type = "application/json"
            elif path == "/":
                payload = self.page(authorized)
            else:
                self.respond(conn, "404 Not Found", "Not found"); return
            self.respond(conn, status, payload, extra, content_type)
        except (OSError, ValueError, RuntimeError):
            pass
        finally:
            conn.close()

    @staticmethod
    def respond(conn, status, content, extra="", content_type="text/html; charset=utf-8"):
        payload = content.encode("utf-8")
        header = "HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\nCache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\nReferrer-Policy: same-origin\r\nContent-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'\r\n%s\r\n" % (status, content_type, len(payload), extra)
        data = header.encode("utf-8") + payload
        sent = 0
        while sent < len(data):
            size = conn.send(memoryview(data)[sent:])
            if not size:
                raise OSError("Connection closed")
            sent += size

"""Desktop HTTPS transport and device metadata for the shared API client."""
import json
import platform
import ssl
import urllib.error
import urllib.request

from .core import BASE, PATHS, Client


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, newurl):
        return None


class Transport:
    def __init__(self, opener=None):
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()))

    def __call__(self, method, url, body, headers):
        if url not in (BASE + path for path in PATHS):
            raise ValueError("Unsupported API destination")
        data = None
        headers = dict(headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            response = self.opener.open(request, timeout=25)
        except urllib.error.HTTPError as error:
            response = error
        except (OSError, urllib.error.URLError):
            raise RuntimeError("Could not connect to U Mobile. Check your connection and try again.") from None
        with response:
            status = response.code
            content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise RuntimeError("U Mobile returned an oversized response")
        try:
            payload = json.loads(content)
        except (ValueError, UnicodeError):
            raise RuntimeError("U Mobile returned an unfamiliar response") from None
        if not isinstance(payload, dict):
            raise RuntimeError("U Mobile returned an unfamiliar response")
        return status, payload


class DesktopClient(Client):
    @staticmethod
    def device_info():
        system = platform.system()
        return {"platform": "IOS", "osVersion": system + " " + platform.release(),
                "appVersion": "4.0.2", "manufacturer": "Desktop",
                "model": {"Windows": "Windows PC", "Linux": "Linux PC", "Darwin": "Mac"}.get(system, "Desktop")}

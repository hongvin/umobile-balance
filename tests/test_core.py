import contextlib
import io
import json
import time
import unittest
from umobile_balance.core import Client, StateStore, APIError, parse_balance
from esp32.portal import parse_form, escape

QUOTA = {"data": {"planName": "U Home 5G", "balances": [
    {"name": "Money", "type": "MONEY", "balance": "10"},
    {"name": "ULTRA Home 5G", "type": "DATA", "category": "PLAN", "consumed": "4294967296",
     "originalBalance": "1073741824000", "balance": "1069446856704"}]}}


class Transport:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
    def __call__(self, method, url, body, headers):
        self.calls.append((method, url, body, headers))
        if not self.replies:
            raise AssertionError("Unexpected extra request")
        return self.replies.pop(0)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.nvm = bytearray(8192)
        self.store = StateStore(self.nvm)

    def test_identity_survives_reboot_and_corruption_detected(self):
        device = self.store.state["deviceId"]
        self.assertEqual(StateStore(self.nvm).state["deviceId"], device)
        self.nvm[20] ^= 1
        recovered = StateStore(self.nvm)
        self.assertNotEqual(recovered.state["deviceId"], device)

    def test_ordinary_primary_approval(self):
        transport = Transport([
            (422, {"errorCode": "LOGIN_BIND_DEVICE_VERIFY", "data": {"secretToken": "BIND_SECRET", "expiresIn": 300}}),
            (201, {"data": {"sessionId": "SESSION", "sseToken": "SSE_ONLY", "expiresIn": 180}}),
            (201, {"data": {"approved": False, "pending": True}}),
            (201, {"data": {"approved": True, "pending": False}}),
            (201, {"data": {"accessToken": "ACCESS", "refreshToken": "REFRESH", "expiresIn": 3600}}),
            (200, QUOTA),
        ])
        client = Client(self.store, transport)
        self.assertFalse(client.login("test@example.invalid", "a + & = password"))
        self.assertEqual(transport.calls[0][2]["password"], "a + & = password")
        self.assertNotIn("Authorization", transport.calls[0][3])
        client.request_primary()
        self.assertFalse(client.poll_approval())
        self.assertTrue(client.poll_approval())
        self.assertTrue(client.signed_in)
        for call in transport.calls[1:5]:
            self.assertEqual(call[3]["Authorization"], "Bearer BIND_SECRET")
        self.assertEqual(set(transport.calls[1][2]), {"deviceId", "platform", "osVersion", "appVersion", "manufacturer", "model", "type"})
        self.assertEqual(transport.calls[1][2]["type"], "PRIMARY")
        self.assertEqual(transport.calls[4][2], {"deviceId": client.device_id, "sessionId": "SESSION"})
        self.assertAlmostEqual(client.balance()["usedGB"], 4.0, places=6)
        self.assertEqual(transport.calls[-1][0], "GET")
        self.assertEqual(transport.calls[-1][3]["Authorization"], "Bearer ACCESS")
        raw = bytes(self.nvm)
        self.assertNotIn(b"BIND_SECRET", raw)
        self.assertNotIn(b"password", raw)
        self.assertTrue(Client(StateStore(self.nvm), Transport([])).signed_in)

    def test_approval_requires_true_boolean(self):
        transport = Transport([(201, {"data": {"approved": False, "pending": False, "status": "APPROVED"}})])
        client = Client(self.store, transport)
        client.approval = {"secret": "B", "sessionId": "S", "expires": time.monotonic() + 100}
        with self.assertRaises(RuntimeError):
            client.poll_approval()
        self.assertEqual(len(transport.calls), 1)
        self.assertFalse(client.signed_in)

    def test_token_rotation_persisted_before_retry(self):
        transport = Transport([(401, {}), (200, {"data": {"accessToken": "NEW_A", "refreshToken": "NEW_R"}}), (200, QUOTA)])
        client = Client(self.store, transport)
        client.accept_tokens({"accessToken": "OLD_A", "refreshToken": "OLD_R"})
        client.balance()
        self.assertEqual(transport.calls[1][2], {"refreshToken": "OLD_R"})
        self.assertNotIn("Authorization", transport.calls[1][3])
        self.assertEqual(transport.calls[2][3]["Authorization"], "Bearer NEW_A")
        self.assertEqual(StateStore(self.nvm).state["refreshToken"], "NEW_R")

    def test_no_repeated_refresh_loop(self):
        transport = Transport([(401, {}), (200, {"accessToken": "B", "refreshToken": "S"}), (401, {})])
        client = Client(self.store, transport)
        client.accept_tokens({"accessToken": "A", "refreshToken": "R"})
        with self.assertRaises(APIError):
            client.balance()
        self.assertEqual(len(transport.calls), 3)
        self.assertEqual(StateStore(self.nvm).state["refreshToken"], "S")

    def test_refresh_expiry_and_rejected_refresh(self):
        transport = Transport([(401, {})])
        client = Client(self.store, transport)
        client.accept_tokens({"accessToken": "A", "refreshToken": "R", "expiresIn": 1})
        identity = client.device_id
        with self.assertRaises(APIError):
            client.balance()
        self.assertFalse(client.signed_in)
        self.assertEqual(client.device_id, identity)
        self.assertTrue(transport.calls[0][1].endswith("/refresh"))

    def test_oversized_session_keeps_previous_persistent_state(self):
        client = Client(self.store, Transport([]))
        client.accept_tokens({"accessToken": "A", "refreshToken": "R"})
        with self.assertRaises(RuntimeError):
            client.accept_tokens({"accessToken": "B" * 9000, "refreshToken": "S"})
        self.assertEqual(client.store.state["accessToken"], "A")
        self.assertEqual(StateStore(self.nvm).state["accessToken"], "A")

    def test_quantities_and_form_encoding(self):
        balance = parse_balance(QUOTA)
        self.assertEqual("%.2f" % balance["usedGB"], "4.00")
        self.assertEqual("%.2f" % balance["totalGB"], "1000.00")
        self.assertEqual("%.2f" % balance["remainingGB"], "996.00")
        self.assertEqual(parse_form(b"password=a+%2B+%26+%3D+pass%F0%9F%8C%9F")["password"], "a + & = pass🌟")
        self.assertNotIn("<", escape('<script>"'))


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()) as logs:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoreTests))
    assert "BIND_SECRET" not in logs.getvalue()
    print(json.dumps({"passed": result.wasSuccessful(), "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors)}))
    raise SystemExit(0 if result.wasSuccessful() else 1)

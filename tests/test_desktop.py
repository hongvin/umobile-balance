import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from umobile_balance.core import BASE
from umobile_balance.desktop import NoRedirect, Transport
from umobile_balance.storage import SessionStore, SERVICE, ACCOUNT
from tools.install_esp32 import install


class Backend:
    def __init__(self): self.value = None
    def get_password(self, service, account): return self.value
    def set_password(self, service, account, value): self.value = value
    def delete_password(self, service, account): self.value = None


class StoreTests(unittest.TestCase):
    def test_memory_mode_never_writes_tokens_or_password_to_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SessionStore(directory)
            identity=store.state['deviceId']
            store.state.update(accessToken='TEST_ACCESS',refreshToken='TEST_REFRESH',password='TEST_PASSWORD')
            store.save()
            content=Path(directory,'identity.json').read_text()
            self.assertNotIn('TEST_',content)
            self.assertEqual(SessionStore(directory).state,{'deviceId':identity})

    def test_remember_rotates_only_in_credential_store_and_signout_clears_it(self):
        backend=Backend()
        with tempfile.TemporaryDirectory() as directory:
            store=SessionStore(directory,backend);store.remember=True
            identity=store.state['deviceId']
            store.state.update(accessToken='TEST_ACCESS',refreshToken='TEST_REFRESH',password='NOT_SAVED')
            store.save()
            self.assertNotIn('NOT_SAVED',backend.value)
            self.assertNotIn('TEST_',Path(directory,'identity.json').read_text())
            loaded=SessionStore(directory,backend)
            self.assertEqual(loaded.state['refreshToken'],'TEST_REFRESH')
            loaded.state['refreshToken']='ROTATED';loaded.save()
            self.assertEqual(SessionStore(directory,backend).state['refreshToken'],'ROTATED')
            loaded.state={'deviceId':identity};loaded.save()
            self.assertIsNone(backend.value)
            self.assertEqual(SessionStore(directory,backend).state,{'deviceId':identity})

    def test_missing_native_backend_fails_before_login_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SessionStore(directory);store.remember=True
            with patch('umobile_balance.storage.native_backend',side_effect=RuntimeError('Unavailable')):
                with self.assertRaises(RuntimeError):store.save()
            self.assertFalse(json.loads(store.path.read_text())['remember'])


class Response(io.BytesIO):
    code=200


class Opener:
    def __init__(self,reply):self.reply=reply;self.calls=[]
    def open(self,request,timeout):
        self.calls.append(request)
        if isinstance(self.reply,Exception):raise self.reply
        return Response(self.reply)


class TransportTests(unittest.TestCase):
    def test_foreign_destination_is_rejected_before_any_request(self):
        opener=Opener(b'{}')
        with self.assertRaises(ValueError):Transport(opener)('GET','https://example.com',None,{'Authorization':'Bearer TEST'})
        self.assertEqual(opener.calls,[])

    def test_redirect_does_not_forward_bearer(self):
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://example.com'))
        error=urllib.error.HTTPError(BASE+'/user/v1/balance',302,'Redirect',{},io.BytesIO(b'{}'))
        opener=Opener(error)
        status,payload=Transport(opener)('GET',BASE+'/user/v1/balance',None,{'Authorization':'Bearer TEST'})
        self.assertEqual(status,302);self.assertEqual(len(opener.calls),1)

    def test_invalid_response_is_not_returned_as_quota(self):
        for content in (b'<html>login</html>',b'[]'):
            with self.assertRaises(RuntimeError):Transport(Opener(content))('GET',BASE+'/user/v1/balance',None,{})


class InstallerTests(unittest.TestCase):
    def test_install_preserves_wifi_and_unrelated_files_and_uses_shared_core(self):
        with tempfile.TemporaryDirectory() as directory:
            drive=Path(directory)
            (drive/'boot_out.txt').write_text('Adafruit CircuitPython 9.0.4; Adafruit Feather ESP32-S3 TFT')
            (drive/'settings.toml').write_text('existing private Wi-Fi settings')
            (drive/'unrelated.txt').write_text('keep')
            install(drive)
            self.assertEqual((drive/'settings.toml').read_text(),'existing private Wi-Fi settings')
            self.assertEqual((drive/'unrelated.txt').read_text(),'keep')
            root=Path(__file__).resolve().parents[1]
            self.assertEqual((drive/'umobile_core.py').read_bytes(),(root/'umobile_balance/core.py').read_bytes())
            self.assertTrue((drive/'lib/adafruit_display_text/label.py').exists())

    def test_wrong_drive_is_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):install(directory)
            self.assertEqual(list(Path(directory).iterdir()),[])

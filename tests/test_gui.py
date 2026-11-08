import os
import time
import unittest
from unittest.mock import patch


class GuiTests(unittest.TestCase):
    def setUp(self):
        if os.environ.get('REQUIRE_TK') != '1' and os.environ.get('RUN_GUI_TESTS') != '1':
            self.skipTest('Set RUN_GUI_TESTS=1 on a desktop to run native Tk window tests')
        try:
            import tkinter as tk
            from tkinter import ttk
            self.tk,self.ttk=tk,ttk
            self.root=tk.Tk();self.root.withdraw()
        except Exception as error:
            if os.environ.get('REQUIRE_TK')=='1':raise
            self.skipTest('Tk/display unavailable: '+str(error))

    def tearDown(self):
        if hasattr(self,'window'):self.window.close()
        elif hasattr(self,'root'):self.root.destroy()

    def test_demo_window_has_no_account_store_and_shows_sample_balance(self):
        from umobile_balance.app import Window
        self.window=Window(self.root,self.tk,self.ttk,demo=True)
        self.root.update()
        self.assertIsNone(self.window.store)
        self.assertEqual(self.window.remaining.cget('text'),'958.00 GB')
        self.assertIn('DEMO',self.window.message.get())

    def test_login_runs_off_ui_thread_clears_password_and_renders_balance(self):
        from umobile_balance.app import Window
        class Store:
            remember=False;load_error=''
            def __init__(self):self.state={'deviceId':'TEST_DEVICE'}
            def save(self):pass
        replies=[(200,{'data':{'accessToken':'TEST_ACCESS','refreshToken':'TEST_REFRESH'}}),
                 (200,{'data':{'planName':'Test plan','balances':[{'type':'DATA','category':'PLAN','consumed':1073741824,'originalBalance':10737418240,'balance':9663676416}]}})]
        def wire(*args):return replies.pop(0)
        with patch('umobile_balance.app.SessionStore',Store),patch('umobile_balance.app.Transport',return_value=wire):
            self.window=Window(self.root,self.tk,self.ttk)
        self.window.email.set('test@example.invalid');self.window.password.set('NOT_REAL')
        self.window.login()
        self.assertEqual(self.window.password.get(),'')
        deadline=time.monotonic()+5
        while self.window.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(self.window.busy)
        self.assertEqual(self.window.remaining.cget('text'),'9.00 GB')

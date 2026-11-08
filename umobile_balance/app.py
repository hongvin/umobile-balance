"""Portable floating desktop window and terminal client."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import contextlib
import getpass
import json
import queue
import sys
import time

from .desktop import DesktopClient, Transport
from .storage import SessionStore

DEMO = {"plan": "U Home 5G — DEMO", "name": "Sample allowance",
        "usedGB": 42.0, "totalGB": 1000.0, "remainingGB": 958.0,
        "expiry": "Sample data", "updatedAt": 0}


class Window:
    def __init__(self, root, tk, ttk, demo=False):
        self.root, self.tk, self.ttk, self.demo = root, tk, ttk, demo
        self.store = None if demo else SessionStore()
        self.client = None if demo else DesktopClient(self.store, Transport())
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.events = queue.Queue()
        self.busy = False
        self.closed = False
        self.timers = set()
        self.last_success = None
        root.title("U Mobile Balance" + (" — DEMO" if demo else ""))
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.frame = ttk.Frame(root, padding=24); self.frame.pack(fill="both", expand=True)
        ttk.Label(self.frame, text="U Mobile", font=("TkDefaultFont", 22, "bold")).pack(anchor="w")
        ttk.Label(self.frame, text="Home broadband data balance").pack(anchor="w", pady=(0, 18))
        self.login_frame = ttk.Frame(self.frame)
        self.email, self.password = tk.StringVar(), tk.StringVar()
        ttk.Label(self.login_frame, text="MyUMobile broadband email").pack(anchor="w")
        ttk.Entry(self.login_frame, textvariable=self.email, width=35).pack(fill="x", pady=(3, 10))
        ttk.Label(self.login_frame, text="Password").pack(anchor="w")
        password_entry = ttk.Entry(self.login_frame, textvariable=self.password, show="•", width=35)
        password_entry.pack(fill="x", pady=(3, 10)); password_entry.bind("<Return>", lambda event: self.login())
        self.remember = tk.BooleanVar(value=self.store.remember if self.store else False)
        ttk.Checkbutton(self.login_frame, text="Keep me signed in using OS credential storage", variable=self.remember).pack(anchor="w")
        ttk.Label(self.login_frame, text="Your password is never saved.").pack(anchor="w", pady=6)
        self.login_button = ttk.Button(self.login_frame, text="Sign in", command=self.login)
        self.login_button.pack(fill="x", pady=(5, 12))
        self.balance_frame = ttk.Frame(self.frame)
        self.plan = ttk.Label(self.balance_frame, text=""); self.plan.pack(anchor="w")
        self.remaining = ttk.Label(self.balance_frame, text="—", font=("TkDefaultFont", 36, "bold"))
        self.remaining.pack(anchor="w", pady=(8, 0))
        ttk.Label(self.balance_frame, text="Remaining").pack(anchor="w")
        self.metrics = ttk.Label(self.balance_frame, text=""); self.metrics.pack(anchor="w", pady=(15, 5))
        self.progress = ttk.Progressbar(self.balance_frame, maximum=100, length=310); self.progress.pack(fill="x", pady=5)
        self.expiry = ttk.Label(self.balance_frame, text=""); self.expiry.pack(anchor="w", pady=(5, 10))
        self.refresh_button = ttk.Button(self.balance_frame, text="Refresh", command=self.refresh)
        self.refresh_button.pack(fill="x", pady=5)
        self.signout_button = ttk.Button(self.balance_frame, text="Sign out", command=self.signout)
        self.signout_button.pack(fill="x", pady=(0, 12))
        self.message = tk.StringVar(value="DEMO · sample data; no account or network access." if demo else self.store.load_error or "Sign in and approve this device in MyUMobile.")
        self.status_label = ttk.Label(self.frame, textvariable=self.message, wraplength=320)
        self.status_label.pack(anchor="w", pady=(5, 12))
        self.topmost = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.frame, text="Keep window on top", variable=self.topmost,
                        command=lambda: root.attributes("-topmost", self.topmost.get())).pack(anchor="w")
        ttk.Label(self.frame, text="Updates every 5 minutes while running.").pack(anchor="w", pady=(10, 0))
        if demo:
            self.render(dict(DEMO, updatedAt=time.time()))
            self.refresh_button.state(["disabled"]); self.signout_button.state(["disabled"])
        elif self.client.signed_in:
            self.balance_frame.pack(before=self.status_label, fill="x")
            self.refresh()
        else:
            self.login_frame.pack(before=self.status_label, fill="x")
        self.later(100, self.drain)
        self.later(300000, self.tick)

    def later(self, delay, operation):
        timer = self.root.after(delay, lambda: (self.timers.discard(timer), operation()))
        self.timers.add(timer)

    def submit(self, operation, callback):
        if self.busy or self.closed:
            return
        self.busy = True
        for widget in (self.login_button, self.refresh_button, self.signout_button): widget.state(["disabled"])
        def work():
            try: self.events.put((callback, operation(), None))
            except Exception as error: self.events.put((callback, None, error))
        self.executor.submit(work)

    def drain(self):
        if self.closed: return
        try:
            callback, value, error = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for widget in (self.login_button, self.refresh_button, self.signout_button): widget.state(["!disabled"])
            if error:
                self.message.set(str(error))
                if self.last_success is not None:
                    self.message.set("Last reading kept; refresh failed. " + str(error))
                if self.client and not self.client.signed_in and not self.client.approval:
                    self.balance_frame.pack_forget(); self.login_frame.pack(before=self.status_label, fill="x")
            else:
                callback(value)
        self.later(100, self.drain)

    def login(self):
        if self.busy or self.demo: return
        email, password = self.email.get().strip(), self.password.get()
        if not email or not password:
            self.message.set("Enter your broadband email and password."); return
        remember = self.remember.get()
        self.password.set("")
        def operation():
            self.store.remember = remember
            self.store.save()  # Check credential storage before sending a login.
            if self.client.login(email, password): return self.client.balance()
            self.client.request_primary()
            return None
        self.message.set("Signing in…")
        self.submit(operation, self.logged_in)

    def logged_in(self, balance):
        if balance is not None:
            self.email.set(""); self.render(balance)
        else:
            self.message.set("Open MyUMobile on your primary phone and approve this computer. Waiting for approval…")
            self.later(10000, self.poll)

    def poll(self):
        if self.closed or not self.client.approval: return
        if self.busy:
            self.later(1000, self.poll); return
        def operation():
            return self.client.balance() if self.client.poll_approval() else None
        self.submit(operation, self.logged_in)

    def refresh(self):
        if not self.demo and self.client.signed_in:
            self.message.set("Refreshing…"); self.submit(self.client.balance, self.render)

    def tick(self):
        if self.closed: return
        if not self.busy and not self.demo: self.refresh()
        self.later(300000, self.tick)

    def render(self, balance):
        self.login_frame.pack_forget()
        if not self.balance_frame.winfo_manager():
            self.balance_frame.pack(before=self.status_label, fill="x")
        self.plan.configure(text=balance["plan"])
        self.remaining.configure(text="%.2f GB" % balance["remainingGB"])
        self.metrics.configure(text="Used %.2f GB     Allowance %.2f GB" % (balance["usedGB"], balance["totalGB"]))
        self.progress["value"] = min(100, max(0, balance["usedGB"] / balance["totalGB"] * 100))
        self.expiry.configure(text="Expires " + balance.get("expiry", "—"))
        self.last_success = time.time()
        if not self.demo: self.message.set("Updated " + time.strftime("%H:%M:%S") + " · directly from U Mobile")

    def signout(self):
        if self.busy or self.demo: return
        def done(value):
            self.balance_frame.pack_forget(); self.login_frame.pack(before=self.status_label, fill="x")
            self.last_success = None; self.message.set("Signed out on this computer.")
        self.submit(self.client.sign_out, done)

    def close(self):
        self.closed = True
        for timer in self.timers: self.root.after_cancel(timer)
        self.timers.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def cli(args):
    if args.demo:
        print(json.dumps(dict(DEMO, updatedAt=time.time()), indent=2)); return
    store = SessionStore()
    if args.remember:
        store.remember = True
    client = DesktopClient(store, Transport())
    if args.sign_out:
        client.sign_out(); print("Signed out on this computer."); return
    with contextlib.redirect_stdout(sys.stderr):
        if not client.signed_in:
            store.save()
            email = input("MyUMobile broadband email: ")
            password = getpass.getpass("Password: ")
            try: approved = client.login(email, password)
            finally: password = ""
            if not approved:
                client.request_primary()
                print("Approve this computer in MyUMobile on your primary phone.")
                while not client.poll_approval(): time.sleep(10)
        balance = client.balance()
    if args.json:
        print(json.dumps(balance))
    else:
        print("%s\nUsed %.2f / %.2f GB · %.2f GB remaining" %
              (balance["plan"], balance["usedGB"], balance["totalGB"], balance["remainingGB"]))


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required. Use that interpreter to create the virtual environment.")
    parser = argparse.ArgumentParser(description="U Mobile balance desktop window or terminal reading")
    parser.add_argument("--cli", action="store_true", help="Print one balance without opening a window")
    parser.add_argument("--json", action="store_true", help="Print the balance as JSON (implies --cli)")
    parser.add_argument("--remember", action="store_true", help="Save CLI tokens in the OS credential store")
    parser.add_argument("--sign-out", action="store_true", help="Clear the Python client's saved login")
    parser.add_argument("--demo", action="store_true", help="Use sample data without credentials or network requests")
    args = parser.parse_args()
    if args.cli or args.json or args.sign_out:
        try: cli(args)
        except (Exception, KeyboardInterrupt) as error: parser.exit(1, str(error) + "\n")
        return
    try:
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
        Window(root, tk, ttk, args.demo)
        root.mainloop()
    except ImportError:
        parser.exit(1, "Tkinter is missing. Install your system's Python Tk package, or use --cli.\n")


if __name__ == "__main__": main()

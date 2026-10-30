"""Update check, verified download and hand-off UI.

All security decisions live in :mod:`updater.core`.  This module only presents
state and never bypasses signature/hash verification.  It degrades gracefully
when the shell does not provide the 2.0 helper methods, so it can also be used
by the 1.7-style window.
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import customtkinter as ctk
from tkinter import messagebox

from .core import UpdateClient, UpdateError, verify_file, verify_manifest, version as parse_version


class UpdateUI:
    def __init__(self, app, version, config_dir):
        self.app = app
        self.directory = Path(config_dir)
        self.client = UpdateClient(version, self.directory / "updates")
        self.busy = False
        self.cancel = threading.Event()
        self.last_release = None
        self.available_release = None
        journal = self.directory / "update-status.json"
        if journal.exists():
            try:
                state = json.loads(journal.read_text(encoding="utf8"))
                if state.get("state") in ("handed-off", "installing") and state.get("version"):
                    if parse_version(version) >= parse_version(state["version"]):
                        self._journal("confirmed", version=state.get("version"))
                    else:
                        self.app.after(
                            2500,
                            lambda: self._notify(
                                "لم يكتمل التحديث السابق. بياناتك محفوظة؛ استخدم فحص التحديثات للمحاولة مجددًا.",
                                "The previous update did not complete. Your data is preserved. Use Check for Updates to retry.",
                            ),
                        )
            except (ValueError, KeyError, OSError, UpdateError):
                pass

    # -- shell integration ------------------------------------------------
    def _t(self, ar, en):
        try:
            return self.app.t(ar, en)
        except Exception:
            return en

    def _dialog_text(self, ar, en):
        """Return logical-order Unicode text for native Tk message boxes.

        The app's t() method reshapes Arabic for custom widgets; native
        message boxes need the original Arabic instead.
        """
        return ar if getattr(self.app, "is_arabic", False) else en

    def _notify(self, ar, en, kind="info"):
        title = self._dialog_text("التحديثات", "Updates")
        text = self._dialog_text(ar, en)
        if kind == "error":
            messagebox.showerror(title, text)
        elif kind == "warning":
            messagebox.showwarning(title, text)
        else:
            messagebox.showinfo(title, text)

    def _ask(self, ar, en):
        return messagebox.askyesno(
            self._dialog_text("التحديثات", "Updates"),
            self._dialog_text(ar, en),
        )

    def _chip(self, text, state="idle"):
        setter = getattr(self.app, "set_update_state", None)
        if setter is None:
            return
        try:
            setter(text, state)
        except Exception:
            pass

    def _journal(self, state, **values):
        self.directory.mkdir(parents=True, exist_ok=True)
        payload = {"state": state, "time": time.time(), **values}
        target = self.directory / "update-status.json"
        temporary = target.with_suffix(".tmp")
        try:
            temporary.write_text(json.dumps(payload), encoding="utf8")
            os.replace(temporary, target)
        except OSError:
            pass

    def dispatch(self, callback):
        try:
            self.app._ui_callbacks.put(callback)
        except Exception:
            callback()

    # -- check ------------------------------------------------------------
    def check(self, manual=True):
        if self.busy:
            return
        self.busy = True
        self.cancel.clear()
        current = getattr(self.client, "current", "")
        self._chip(self._t("جارٍ فحص التحديثات…", "Checking for updates…"), "checking")
        prereleases = bool(self.app.settings.get("allow_prereleases", False))

        def work():
            try:
                release = self.client.check(prereleases)
                self.dispatch(lambda: self._checked(release, manual, current))
            except Exception as exc:
                error = str(exc)
                self.dispatch(lambda: self._check_failed(error, manual))
            finally:
                self.busy = False

        threading.Thread(target=work, daemon=True, name="update-check").start()

    def _checked(self, release, manual, current):
        if not release:
            self.available_release = None
            self._chip(
                f"v{current}  •  " + self._t("محدّث", "Up to date"),
                "idle",
            )
            if manual:
                self._notify(
                    "أنت تستخدم أحدث إصدار مدعوم.",
                    "You are using the latest supported release.",
                )
            return
        self.available_release = release
        self._chip(
            self._t("تحديث متاح ", "Update available ") + release["tag"],
            "available",
        )
        self.show_release(release, manual)

    def _check_failed(self, error, manual):
        self._chip(self._t("تعذر فحص التحديثات", "Update check failed"), "error")
        if manual:
            self._notify(str(error), str(error), "error")

    # -- release dialog ---------------------------------------------------
    def show_release(self, release, manual):
        if not release:
            return
        self.last_release = release
        window = ctk.CTkToplevel(self.app)
        window.title(self._t("تحديث موثّق ", "Verified update ") + release["tag"])
        window.geometry("620x480")
        window.transient(self.app)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            window,
            text=self._t("تحديث موثّق ", "Verified update ") + release["tag"],
            font=("Segoe UI", 17, "bold"),
        ).grid(row=0, column=0, padx=20, pady=(16, 4), sticky="w")
        ctk.CTkLabel(
            window,
            text=self._t(
                "لن يُثبَّت أي ملف قبل التحقق من التوقيع والبصمة.",
                "Nothing is installed until the signature and digest are verified.",
            ),
            font=("Segoe UI", 10),
            text_color="gray",
        ).grid(row=1, column=0, padx=20, pady=(0, 8), sticky="w")

        notes = ctk.CTkTextbox(window, wrap="word")
        notes.grid(row=2, column=0, sticky="nsew", padx=20, pady=4)
        notes.insert("1.0", release.get("notes") or self._t("لا توجد ملاحظات إصدار.", "No release notes."))
        notes.configure(state="disabled")

        bar = ctk.CTkProgressBar(window)
        bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(10, 4))
        bar.set(0)
        status = ctk.CTkLabel(
            window,
            text=self._t("تم التحقق من التحديث. نزّله للمتابعة.", "Signed update verified. Download to continue."),
            font=("Segoe UI", 11),
        )
        status.grid(row=4, column=0, pady=2)

        button = ctk.CTkButton(window, text=self._t("تنزيل التحديث", "Download update"), command=lambda: None)
        button.grid(row=5, column=0, pady=(8, 4))

        def download():
            if self.busy:
                return
            self.busy = True
            self.cancel.clear()
            button.configure(state="disabled", text=self._t("جارٍ التنزيل…", "Downloading…"))
            status.configure(text=self._t("جارٍ تنزيل الملف الموثّق…", "Downloading the verified installer…"))
            self._chip(self._t("جارٍ تنزيل التحديث…", "Downloading update…"), "checking")
            last = [0.0]

            def progress(value):
                now = time.monotonic()
                if value < 1 and now - last[0] < 0.1:
                    return
                last[0] = now
                self.dispatch(lambda: bar.set(value) if bar.winfo_exists() else None)

            def work():
                try:
                    path = self.client.download(release, progress, self.cancel.is_set)
                    self.dispatch(lambda: ready(path))
                except Exception as exc:
                    error = str(exc)
                    self.dispatch(lambda: failed(error))
                finally:
                    self.busy = False

            threading.Thread(target=work, daemon=True, name="update-download").start()

        def ready(path):
            if not window.winfo_exists():
                return
            status.configure(text=self._t("تم التحقق من التنزيل. جاهز للتثبيت.", "Download verified. Ready to install."))
            button.configure(
                state="normal",
                text=self._t("تثبيت وإغلاق Veyora", "Install and close Veyora"),
                command=lambda: self.install(path, release),
                fg_color="#128a55",
                hover_color="#0d6b42",
            )
            self._chip(self._t("التحديث جاهز للتثبيت", "Update ready to install"), "ready")

        def failed(error):
            if not window.winfo_exists():
                return
            status.configure(text=error)
            button.configure(state="normal", text=self._t("إعادة المحاولة", "Retry"), command=download)
            self._chip(self._t("فشل تنزيل التحديث", "Update download failed"), "error")

        button.configure(command=download)

        def close():
            self.cancel.set()
            if self.available_release is not None:
                self._chip(
                    self._t("تحديث متاح ", "Update available ") + self.available_release["tag"],
                    "available",
                )
            window.destroy()

        window.protocol("WM_DELETE_WINDOW", close)
        ctk.CTkButton(window, text=self._t("إلغاء / لاحقًا", "Cancel / later"), command=close).grid(
            row=6, column=0, pady=(0, 14)
        )

    # -- install ----------------------------------------------------------
    def install(self, path, release):
        if not getattr(sys, "frozen", False) or os.name != "nt":
            self._notify(
                "التثبيت مدعوم في تطبيق Windows المجمّع فقط.",
                "Installation is supported in the packaged Windows application only.",
            )
            return
        active = [
            task
            for task in self.app.queue_manager.get_tasks_by_status()
            if task["status"] not in self.app.queue_manager.TERMINAL
        ]
        if active or getattr(self.app, "_local_running", False):
            self._notify(
                "أنهِ التنزيلات أو الترجمة النشطة قبل التثبيت.",
                "Finish or cancel active downloads and translation before installing.",
                "warning",
            )
            return
        try:
            manifest = verify_manifest(release["raw"], release["signature"], self.client.keys, release["tag"])
            verify_file(path, manifest)
        except Exception as exc:
            self._notify(str(exc), str(exc), "error")
            return
        if not self._ask(
            "إغلاق Veyora وتثبيت التحديث الموثّق؟ ستُحفظ بياناتك.",
            "Close Veyora and install the verified update? Your data will be preserved.",
        ):
            return
        import uuid

        backup = self.directory / "backups" / (
            time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        )
        try:
            backup.mkdir(parents=True, exist_ok=True)
            for name in ("settings.json", "history.json", "config.json"):
                source = self.directory / name
                if source.exists():
                    shutil.copy2(source, backup / name)
        except OSError as exc:
            self._notify(
                "تعذر نسخ الإعدادات احتياطيًا؛ أُلغي التثبيت.",
                "Could not back up settings; installation cancelled.",
                "error",
            )
            return
        self._journal("installing", version=release["tag"], installer=str(path), backup=str(backup))
        try:
            subprocess.Popen(
                [sys.executable, "--install-update", str(os.getpid()), str(path), release["tag"]],
                shell=False,
            )
        except OSError as exc:
            self._journal("failed", version=release["tag"], error=str(exc))
            self._notify(
                "تعذر بدء مثبّت التحديث: " + str(exc),
                "Could not start the update installer: " + str(exc),
                "error",
            )
            return
        self._chip(self._t("جارٍ تثبيت التحديث…", "Installing update…"), "checking")
        self.app._on_close()

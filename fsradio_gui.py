#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FSRadio GUI (Tkinter) for Frontier Silicon / UNDOK using afsapi (async, Python 3.12+)

Hardening:
- Never calls API unless connected (strict guards)
- Disconnects volume slider command while initializing to avoid spurious calls
- Proper ttk states (['!disabled']/['disabled'])
- Auto-tries base URLs if you enter only IP/host (…/device, …/fsapi, plain host)
"""

import json
import re
import requests
import socket
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Any, Iterable, Optional, List

import asyncio
from concurrent.futures import Future

try:
    from afsapi import AFSAPI
except ImportError:
    AFSAPI = None

CONFIG_DIR = Path.home() / ".config" / "fsradio-gui"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "url": "192.168.0.153", # you can enter just IP/host; app tries common roots
    "pin": 1234,
    "timeout": 2,
    "last_mode": "IRadio"
}

# -------------------- Async service --------------------
class RadioService:
    def __init__(self):
        self._loop = None
        self._thread = None
        self._api: Optional[AFSAPI] = None
        self._connected = False
        self.url_used: Optional[str] = None
        self.pin = 1234
        self.timeout = 2

    def _ensure_loop(self):
        if self._loop:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def _run_coro(self, coro) -> Any:
        self._ensure_loop()
        fut: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    @staticmethod
    def _normalize_candidates(user_input: str) -> List[str]:
        s = user_input.strip()
        if not s:
            return []
        if not s.startswith(("http://", "https://")):
            s = "http://" + s

        # If user already gave a path with /device or /fsapi, try as-is first.
        if re.search(r"/(device|fsapi)(/)?$", s):
            return [s]

        host_port = s.rstrip("/")
        host_only = host_port.split("//", 1)[1]
        has_port = ":" in host_only
        candidates = [
            (host_port + "/device") if has_port else (host_port + ":80/device"),
            (host_port + "/fsapi")  if has_port else (host_port + ":80/fsapi"),
            host_port,
        ]
        # dedupe
        seen, uniq = set(), []
        for c in candidates:
            if c not in seen:
                uniq.append(c); seen.add(c)
        return uniq

    def connect(self, user_url: str, pin: int, timeout: int = 2):
        if AFSAPI is None:
            raise RuntimeError("Dependency missing: install with `pip install afsapi` in your venv.")
        self.pin = int(pin)
        self.timeout = int(timeout)

        # Optional DNS/IP check
        try:
            host = user_url
            if host.startswith("http"):
                host = host.split("://", 1)[1]
            host = host.split("/", 1)[0]
            socket.gethostbyname(host.split(":")[0])
        except Exception:
            pass

        self._api = None
        self._connected = False
        self.url_used = None
        last_err = None

        for base in self._normalize_candidates(user_url):
            try:
                async def _create():
                    api = await AFSAPI.create(base, self.pin, self.timeout)
                    await api.get_friendly_name()  # probe
                    return api
                api = self._run_coro(_create())
                self._api = api
                self._connected = True
                self.url_used = base
                break
            except Exception as e:
                last_err = e
                continue

        if not self._connected:
            raise RuntimeError(
                "Could not connect to the radio. "
                f"Tried: {', '.join(self._normalize_candidates(user_url))}. Last error: {last_err}"
            )

    def is_connected(self) -> bool:
        return self._connected and self._api is not None

    # ---------- guarded wrappers ----------
    def _require(self):
        if not self.is_connected():
            raise RuntimeError("Not connected to a radio.")

    def get_friendly_name(self) -> str:
        self._require()
        async def _c(): return await self._api.get_friendly_name()
        return self._run_coro(_c())

    def get_power(self) -> bool:
        self._require()
        async def _c(): return await self._api.get_power()
        return bool(self._run_coro(_c()))

    def set_power(self, on: bool):
        self._require()
        async def _c(): return await self._api.set_power(bool(on))
        return self._run_coro(_c())

    def get_volume(self) -> int:
        self._require()
        async def _c(): return await self._api.get_volume()
        return int(self._run_coro(_c()))

    def set_volume(self, value: int):
        self._require()
        async def _c(): return await self._api.set_volume(int(value))
        return self._run_coro(_c())

    def get_modes(self) -> Iterable[str]:
        self._require()
        async def _c(): return await self._api.get_modes()
        return self._run_coro(_c())

    def set_mode(self, mode: str):
        self._require()
        async def _c(): return await self._api.set_mode(mode)
        return self._run_coro(_c())

    def get_presets(self):
        self._require()
        async def _c(): return await self._api.get_presets()
        return self._run_coro(_c())

    def recall_preset(self, preset):
        self._require()
        async def _c(): return await self._api.recall_preset(preset)
        return self._run_coro(_c())


# ------------------------------ GUI ------------------------------
class GuiView(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FSRadio – Remote")
        self.minsize(520, 460)
        self.service = RadioService()
        self.config_data = self._load_config()
        self.preset_buttons = []
        self._during_init = False
        self._vol_cmd = None  # keep original command so we can detach/attach safely

        # Connection
        top = ttk.LabelFrame(self, text="Connection")
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Radio URL or IP:").grid(row=0, column=0, sticky="w", padx=6, pady=6)
        self.url_var = tk.StringVar(value=self.config_data["url"])
        ttk.Entry(top, textvariable=self.url_var, width=40).grid(row=0, column=1, sticky="w", padx=6, pady=6)

        ttk.Label(top, text="PIN:").grid(row=0, column=2, sticky="e", padx=6, pady=6)
        self.pin_var = tk.StringVar(value=str(self.config_data["pin"]))
        ttk.Entry(top, textvariable=self.pin_var, width=8, show="•").grid(row=0, column=3, sticky="w", padx=6, pady=6)

        ttk.Label(top, text="Timeout:").grid(row=0, column=4, sticky="e", padx=6, pady=6)
        self.timeout_var = tk.StringVar(value=str(self.config_data["timeout"]))
        ttk.Entry(top, textvariable=self.timeout_var, width=4).grid(row=0, column=5, sticky="w", padx=6, pady=6)

        self.btn_connect = ttk.Button(top, text="Connect", command=self.on_connect)
        self.btn_connect.grid(row=0, column=6, padx=8, pady=6)

        # Power + Volume
        pframe = ttk.LabelFrame(self, text="Power & Volume")
        pframe.pack(fill="x", padx=10, pady=6)

        self.power_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(pframe, text="Power On", variable=self.power_var, command=self.on_power_toggle).pack(side="left", padx=10, pady=6)

        ttk.Label(pframe, text="Volume").pack(side="left", padx=(16, 4))
        self.vol_slider = ttk.Scale(pframe, from_=0, to=40, orient="horizontal")
        self._vol_cmd = self.on_volume_change
        self.vol_slider.configure(command=self._vol_cmd)
        self.vol_slider.set(10)
        self.vol_slider.pack(side="left", fill="x", expand=True, padx=8)

        # Modes
        mframe = ttk.LabelFrame(self, text="Mode")
        mframe.pack(fill="x", padx=10, pady=6)

        self.mode_combo = ttk.Combobox(mframe, state="readonly")
        self.mode_combo.pack(fill="x", padx=10, pady=6)
        self.mode_combo.bind("<<ComboboxSelected>>", lambda _e: self.on_mode_change())

        # Presets
        prframe = ttk.LabelFrame(self, text="Presets")
        prframe.pack(fill="both", expand=True, padx=10, pady=10)

        self.preset_container = ttk.Frame(prframe)
        self.preset_container.pack(fill="both", expand=True)

        ttk.Button(prframe, text="Reload Presets", command=self.on_load_presets).pack(pady=6)

        # initial state
        self._enable_controls(False)

        # optional auto-connect
        self.after(300, self.on_connect)

    # -------------- config --------------
    def _load_config(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config = {}
        if CONFIG_FILE.exists():
            try:
                config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception:
                pass

        missing = {k: v for k, v in DEFAULT_CONFIG.items() if k not in config or config[k] in ("", None)}
        if missing:
            import tkinter as tk
            from tkinter import simpledialog
            root = tk.Tk()
            root.withdraw()
            for key, default in missing.items():
                prompt = f"Enter {key.replace('_', ' ').title()}:"
                value = simpledialog.askstring("Config Required", prompt, initialvalue=str(default))
                if key == "last_mode":
                  value = get_last_mode_from_api(config.get("url", default), config.get("pin", default))
                elif key in ("pin", "timeout"):
                    try:
                        value = int(value)
                    except Exception:
                        value = default
                config[key] = value if value not in ("", None) else default
            root.destroy()
            try:
                CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        return config

    def _save_config(self):
        self.config_data["url"] = self.url_var.get().strip()
        try:
            self.config_data["pin"] = int(self.pin_var.get().strip())
        except ValueError:
            self.config_data["pin"] = DEFAULT_CONFIG["pin"]
        try:
            self.config_data["timeout"] = int(self.timeout_var.get().strip())
        except ValueError:
            self.config_data["timeout"] = DEFAULT_CONFIG["timeout"]
        try:
            # this is likely wrong as this is the full info block not the short like IRadio
            # TODO: build mechanism to correctly extract and persist this information
            self.config_data["last_mode"] = int(self.mode_combo.get().strip())
        except ValueError:
            self.config_data["last_mode"] = DEFAULT_CONFIG["last_mode"]
        CONFIG_FILE.write_text(json.dumps(self.config_data, ensure_ascii=False, indent=2), encoding="utf-8")

    # -------------- helpers --------------
    def _enable_controls(self, on: bool):
        if on:
            self.vol_slider.state(['!disabled'])
            self.mode_combo.state(['readonly', '!disabled'])
            for b in self.preset_buttons:
                b.state(['!disabled'])
        else:
            self.vol_slider.state(['disabled'])
            self.mode_combo.state(['disabled'])
            for b in self.preset_buttons:
                b.state(['disabled'])

    def _async_call(self, func, *args, on_error: Optional[callable] = None):
        def worker():
            try:
                func(*args)
            except Exception as ex:
                err = ex  # bind into closure
                self.after(0, lambda err=err: (on_error(err) if on_error else messagebox.showerror("Error", str(err))))
        threading.Thread(target=worker, daemon=True).start()

    # -------------- events --------------
    def on_connect(self):
        url = self.url_var.get().strip()
        pin = self.pin_var.get().strip()
        timeout = self.timeout_var.get().strip()

        self._enable_controls(False)
        self._during_init = True
        # detach slider command during init to prevent spurious callbacks
        self.vol_slider.configure(command=None)

        def after_ok():
            try:
                name = self.service.get_friendly_name()
                v = self.service.get_volume()
                # set slider without callback
                self.vol_slider.set(v)
                self.power_var.set(self.service.get_power())
                modes = list(self.service.get_modes())
                self.mode_combo["values"] = modes
                last_mode = self.config_data.get("last_mode")
                if last_mode in modes:
                    self.mode_combo.set(last_mode)
                elif modes:
                    self.mode_combo.current(0)
                self._enable_controls(True)
                self._save_config()
                self.on_load_presets()
                used = self.service.url_used or url
                self.title(f"FSRadio – {name} [{used}]")
            except Exception as ex:
                messagebox.showerror("Init error", str(ex))
            finally:
                # re-attach slider command after init
                self.vol_slider.configure(command=self._vol_cmd)
                self._during_init = False

        def do_connect():
            try:
                self.service.connect(url, int(pin), int(timeout))
                self.after(0, after_ok)
            except Exception as ex:
                err = ex
                self.after(0, lambda err=err: (messagebox.showerror("Connection failed", str(err)),
                                               self.vol_slider.configure(command=self._vol_cmd),
                                               setattr(self, "_during_init", False)))

        threading.Thread(target=do_connect, daemon=True).start()

    def on_power_toggle(self):
        if not self.service.is_connected():
            return
        on = bool(self.power_var.get())
        self._async_call(self.service.set_power, on)

    def on_volume_change(self, _evt=None):
        if self._during_init or not self.service.is_connected():
            return
        v = int(float(self.vol_slider.get()))
        self._async_call(self.service.set_volume, v)

    def on_mode_change(self):
        if not self.service.is_connected():
            return
        mode = self.mode_combo.get()
        self.config_data["last_mode"] = mode
        self._save_config()
        self._async_call(self.service.set_mode, mode)

    def on_load_presets(self):
        for child in self.preset_container.winfo_children():
            child.destroy()
        self.preset_buttons = []

        if not self.service.is_connected():
            return

        def build_buttons(presets):
            for idx, p in enumerate(presets, start=1):
                label = None
                if isinstance(p, dict):
                    label = p.get("name") or p.get("label") or p.get("title")
                if not label:
                    label = f"Preset {idx}"
                b = ttk.Button(self.preset_container, text=label, command=lambda pv=p: self.on_preset(pv))
                b.pack(fill="x", padx=6, pady=3)
                self.preset_buttons.append(b)
            self._enable_controls(True)

        def worker():
            try:
                presets = self.service.get_presets()
                self.after(0, lambda presets=presets: build_buttons(presets))
            except Exception as ex:
                err = ex
                self.after(0, lambda err=err: messagebox.showerror("Presets error", str(err)))

        threading.Thread(target=worker, daemon=True).start()

    def on_preset(self, preset):
        if not self.service.is_connected():
            return
        self._async_call(self.service.recall_preset, preset)


def get_last_mode_from_api(url, pin):
    try:
        # Example endpoint; adjust as needed for your API
        response = requests.get(f"{url}/api/status", params={"pin": pin}, timeout=5)
        response.raise_for_status()
        data = response.json()
        # Adjust key as needed based on API response structure
        return data.get("mode", "DAB")
    except Exception:
        return "DAB"

if __name__ == "__main__":
    app = GuiView()
    app.mainloop()

from __future__ import annotations

import json
import logging
import os
import queue
import socket
import threading
import time

import serial
from serial.tools import list_ports

from .context import ContextService
from .render import Renderer
from .store import Store

LOG = logging.getLogger("enki.device")
# Exceeds the firmware raw-frame receiver's 15-second inter-byte gap.
USB_RECOVERY_SECONDS = 20
USB_BOOT_SECONDS = 3


def ports() -> list[str]:
    return [
        p.device
        for p in list_ports.comports()
        if p.vid is not None and ("usbserial" in p.device or "usbmodem" in p.device)
    ]


def local_address() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]


class DeviceBridge:
    """One serial owner. USB and Wi-Fi use the same immutable frames and review IDs."""

    def __init__(self, store: Store, context: ContextService, renderer: Renderer):
        self.store, self.context, self.renderer = store, context, renderer
        self.commands = queue.Queue()
        self.stop = threading.Event()
        self.thread = None
        self.message = "USB is not connected."
        self.last_status = {}
        self.port = None
        self.io = None
        self.last_batch = 0
        self.refresh_on_connect = False
        self.known_frames = set()
        self.transferring = False
        self.resume_after = 0.0
        self.deferred_acks = []
        self.identified = False
        self.expected_id = None
        self.pair_lock = threading.Lock()
        self.lifecycle_lock = threading.RLock()
        self.serial_close_lock = threading.Lock()

    def start(self, port: str | None = None, automatic=False, expected_id=None):
        with self.lifecycle_lock:
            if self.thread and self.thread.is_alive():
                if not self.stop.is_set() and (automatic or self.identified):
                    return
                self.close()
                self.thread.join(timeout=3)
                if self.thread.is_alive():
                    raise ValueError("USB is still closing. Try Connect again in a moment.")
            available = ports()
            if port is None:
                if len(available) != 1:
                    raise ValueError("Connect one Inkplate by USB, then try again.")
                port = available[0]
            if port not in available and not automatic:
                raise ValueError("That USB device is not available.")
            self.port = port
            self.expected_id = expected_id or self.expected_id
            self.message = "Waiting for the Inkplate…"
            self.stop.clear()
            self.thread = threading.Thread(target=self.run, daemon=True, name="enki-usb")
            self.thread.start()

    @property
    def pairing_file(self):
        return self.store.config.data / "usb-device.json"

    def restore(self):
        try:
            saved = json.loads(self.pairing_file.read_text())
        except (OSError, ValueError):
            return
        if (
            isinstance(saved, dict)
            and saved.get("enabled") is True
            and isinstance(saved.get("port"), str)
            and isinstance(saved.get("device_id"), str)
        ):
            # A previous process may have died in the middle of a raw frame.
            self.resume_after = time.monotonic() + USB_RECOVERY_SECONDS
            self.start(saved["port"], automatic=True, expected_id=saved["device_id"])

    def remember(self, enabled):
        with self.pair_lock:
            if enabled and self.stop.is_set():
                return
            value = {"enabled": enabled, "port": self.port, "device_id": self.expected_id}
            temporary = self.pairing_file.with_suffix(".tmp")
            fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(value, stream)
            temporary.replace(self.pairing_file)

    def disconnect(self):
        with self.lifecycle_lock:
            self.close()
            while True:
                try:
                    self.commands.get_nowait().clear()
                except queue.Empty:
                    break
            self.remember(False)
            if self.thread and self.thread.is_alive():
                self.thread.join(timeout=3)
                if self.thread.is_alive():
                    self.message = "USB is still closing. Try Disconnect again in a moment."
                    raise ValueError(self.message)
            self.expected_id = None
            self.message = "USB disconnected. The port is free for flashing."

    def close(self):
        with self.lifecycle_lock:
            self.stop.set()
            if self.transferring:
                self.resume_after = max(self.resume_after, time.monotonic() + USB_RECOVERY_SECONDS)
            self.identified = False
            connection = self.io
            if connection:
                try:
                    connection.cancel_read()
                    connection.cancel_write()
                except (OSError, serial.SerialException):
                    pass
                self.close_serial(connection)

    def close_serial(self, connection):
        # The worker and explicit Disconnect may finish at the same moment.
        with self.serial_close_lock:
            connection.close()

    def send(self, command):
        self.io.write(
            json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        )

    def receive(self, timeout=1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop.is_set():
            line = self.io.readline()
            if not line:
                continue
            try:
                value = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if isinstance(value, dict):
                return value
        return {}

    def wait_for(self, key, timeout=30, packet=False):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self.stop.is_set():
            reply = self.receive(1)
            if key in reply:
                return reply if packet else reply[key]
            self.handle(reply, allow_batch=False)
            if "error" in reply:
                raise RuntimeError("Inkplate rejected a transfer: " + str(reply["error"]))
        raise TimeoutError("Inkplate did not answer. Check that it is powered on.")

    def upload(self, frame):
        if frame["id"] in self.known_frames:
            return
        data = (self.renderer.frames / (frame["id"] + ".raw")).read_bytes()
        self.transferring = True
        stored = False
        try:
            self.send(
                {"cmd": "frame", "id": frame["id"], "length": len(data), "crc32": frame["crc32"]}
            )
            if self.wait_for("ready", 10) != frame["id"]:
                raise RuntimeError("Frame header was not acknowledged")
            self.io.write(data)
            if self.wait_for("stored", 30) != frame["id"]:
                raise RuntimeError("Frame did not finish storing")
            stored = True
        finally:
            if not stored:
                self.resume_after = max(self.resume_after, time.monotonic() + USB_RECOVERY_SECONDS)
            self.transferring = False
        if self.deferred_acks:
            self.send({"cmd": "ack", "ids": self.deferred_acks})
            self.deferred_acks = []

    def batch(self):
        self.last_batch = time.monotonic()
        self.message = "Sending cards to the Inkplate…"
        # Freeze touch before reading the authoritative card position.
        self.send({"cmd": "prepare"})
        if self.wait_for("prepared", 10) != "ok":
            raise RuntimeError("Inkplate could not prepare storage")
        frozen = self.wait_for("status", 10, packet=True)
        self.last_status = {k: v for k, v in frozen.items() if k != "pending"}
        if frozen.get("storage_ok") is False:
            raise RuntimeError("Inkplate storage did not initialise")
        for event in frozen.get("pending", []):
            self.accept(event)
        self.known_frames = set(frozen.get("frames", [])) if frozen.get("cache_ok") else set()
        context = self.context.snapshot()
        study_settings = self.store.settings()
        revision = study_settings["study_revision"]
        style = study_settings["display_style"]
        cards = self.store.study_cards(2, frozen.get("cards", []))
        batch = {
            "protocol": 1,
            "study_revision": revision,
            "display_style": style,
            "resume_back": bool(frozen.get("back")),
            "server_epoch": int(time.time()),
            "cards": [],
            "context": context,
            "idle": None,
        }
        for card in cards:
            bundle = {"id": card["id"]}
            for side in ("front", "back"):
                bundle[side] = self.renderer.frame(card, side, context, style)
                self.upload(bundle[side])
            batch["cards"].append(bundle)
        if not cards:
            batch["idle"] = self.renderer.frame(None, "front", context, style)
            self.upload(batch["idle"])
        batch["clock_epoch"] = int(time.time())
        self.send({"cmd": "batch", "batch": batch})
        if self.wait_for("installed", 30) != "ok":
            raise RuntimeError("Inkplate could not install the card batch")
        self.known_frames = {
            frame["id"] for card in batch["cards"] for frame in (card["front"], card["back"])
        }
        if batch["idle"]:
            self.known_frames.add(batch["idle"]["id"])
        self.last_batch = time.monotonic()
        self.refresh_on_connect = False
        self.message = (
            "Inkplate connected. Cards and touch controls are ready."
            if frozen.get("touch_ok", True)
            else "Cards loaded. The touchscreen did not initialise."
        )
        self.send({"cmd": "status"})

    def accept(self, event):
        result = self.store.receive_review(event)
        if result.get("rejected"):
            LOG.warning("A device answer was preserved in review recovery")
        identity = event.get("id")
        if not identity:
            return
        if self.transferring:
            self.deferred_acks.append(identity)
        else:
            self.send({"cmd": "ack", "ids": [identity]})

    def handle(self, reply, allow_batch=True):
        if reply.get("status"):
            self.last_status = {k: v for k, v in reply.items() if k != "pending"}
            for event in reply.get("pending", []):
                self.accept(event)
            healthy = reply.get("cache_ok", True)
            self.known_frames = set(reply.get("frames", [])) if healthy else set()
            idle = reply.get("remaining", 0) == 0
            age = time.time() - reply.get("context_epoch", 0)
            expired = reply.get("context_expired", False) or (
                bool(reply.get("context_deadline")) and time.time() >= reply["context_deadline"]
            )
            refresh = (self.refresh_on_connect or age >= 600 or expired) and not reply.get(
                "back", False
            )
            if (
                allow_batch
                and time.monotonic() - self.last_batch >= (60 if idle else 10)
                and (idle or refresh or not healthy)
            ):
                self.batch()
        if "event" in reply:
            self.accept(reply["event"])
        if "need_batch" in reply and allow_batch:
            self.batch()
        if "error" in reply:
            self.message = "Inkplate: " + str(reply["error"])
            LOG.warning(self.message)

    def configure(self, ssid, password, port=8787):
        with self.lifecycle_lock:
            if (
                not self.thread
                or not self.thread.is_alive()
                or not self.identified
                or self.stop.is_set()
            ):
                raise ValueError("Wait for a powered-on enki Inkplate to identify itself over USB.")
            self.commands.put(
                {
                    "cmd": "config",
                    "ssid": ssid,
                    "password": password,
                    "server": f"http://{local_address()}:{port}",
                    "token": self.store.config.token(),
                }
            )

    def run(self):
        while not self.stop.is_set():
            quiet = self.resume_after - time.monotonic()
            if quiet > 0:
                self.message = "Waiting for an interrupted USB transfer to clear…"
                if self.stop.wait(quiet):
                    break
            delay = 5
            try:
                self.io = serial.Serial(port=None, baudrate=115200, timeout=0.3, write_timeout=40)
                self.io.dtr = False
                self.io.rts = False
                self.io.port = self.port
                self.io.open()
                # Opening CH340 can reset the ESP32. Do not send into its boot sequence.
                if self.stop.wait(USB_BOOT_SECONDS):
                    break
                self.identified = False
                self.refresh_on_connect = True
                self.deferred_acks = []
                self.message = "Waiting for the Inkplate…"
                self.send({"cmd": "status"})
                last_poll = time.monotonic()
                while not self.stop.is_set():
                    reply = self.receive(0.5)
                    if reply.get("status"):
                        identity = reply.get("device_id", "")
                        valid = (
                            reply.get("protocol") == 1
                            and isinstance(identity, str)
                            and identity.startswith("inkplate-")
                        )
                        if valid and (not self.expected_id or identity == self.expected_id):
                            if not self.identified:
                                self.message = "Inkplate connected."
                                if reply.get("usb_batch"):
                                    self.send({"cmd": "abort"})
                                self.expected_id = identity
                                self.remember(True)
                            self.identified = True
                        else:
                            self.message = "USB device is not the paired enki Inkplate."
                    if self.identified:
                        # Back off repeated failures; resume_after separately protects unfinished raw reads.
                        delay = USB_RECOVERY_SECONDS
                        self.handle(reply)
                        try:
                            command = self.commands.get_nowait()
                        except queue.Empty:
                            command = None
                        if command:
                            if command.get("cmd") == "config":
                                command["epoch"] = int(time.time())
                            self.send(command)
                            command.clear()
                    if time.monotonic() - last_poll > 5:
                        self.send({"cmd": "status"})
                        last_poll = time.monotonic()
            except Exception as error:
                if not self.stop.is_set():
                    self.message = f"USB retrying: {error}"
                    LOG.warning("USB connection retry: %s", type(error).__name__)
            finally:
                self.identified = False
                if self.io:
                    self.close_serial(self.io)
                self.io = None
            if self.stop.wait(delay):
                break

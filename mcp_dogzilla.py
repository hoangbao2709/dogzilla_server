# -*- coding: utf-8 -*-
import os
import threading
import time

import requests

from . import config

try:
    import serial
except Exception:
    serial = None


IGNORED_CMDS = {0}
TIMEOUT = 5


class Speech:
    def __init__(self, com="/dev/ttyUSB0", baudrate=115200, debug=True):
        self.debug = debug
        self.ser = None
        self.buffer = b""

        if serial is None:
            print("[MCP_Dogzilla] pyserial not available; voice serial disabled")
            return

        try:
            self.ser = serial.Serial(com, baudrate, timeout=0.1)
            if self.ser.isOpen():
                print(f"[MCP_Dogzilla] Speech serial opened: {com} @ {baudrate}")
        except Exception as e:
            print("[MCP_Dogzilla] Speech serial open failed:", e)
            self.ser = None

    def close(self):
        if self.ser and self.ser.isOpen():
            self.ser.close()
            print("[MCP_Dogzilla] Speech serial closed")

    def void_write(self, void_data):
        try:
            if not self.ser:
                return
            void_data = int(void_data)
            cmd = f"$A{void_data:03d}#".encode()
            self.ser.write(cmd)

            if self.debug:
                print("[MCP_Dogzilla] TX:", cmd)

            time.sleep(0.01)
            self.ser.flushInput()
        except Exception as e:
            print("[MCP_Dogzilla] Write error:", e)

    def speech_read(self):
        if not self.ser:
            return 999

        try:
            data = self.ser.read(64)
            if data:
                self.buffer += data

                if self.debug:
                    print("[MCP_Dogzilla] RAW:", data)

                while b"$" in self.buffer and b"#" in self.buffer:
                    start = self.buffer.find(b"$")
                    end = self.buffer.find(b"#", start)

                    if end == -1:
                        break

                    frame = self.buffer[start + 1:end]
                    self.buffer = self.buffer[end + 1:]

                    if self.debug:
                        print("[MCP_Dogzilla] FRAME:", frame)

                    digits = "".join(chr(c) for c in frame if chr(c).isdigit())
                    if digits:
                        cmd = int(digits)

                        if self.debug:
                            print("[MCP_Dogzilla] CMD:", cmd)

                        return cmd

            return 999
        except Exception as e:
            print("[MCP_Dogzilla] Read error:", e)
            return 999


class RobotAPI:
    def __init__(self):
        robot_ip = os.getenv("ROBOT_IP", "127.0.0.1")
        robot_port = os.getenv("ROBOT_PORT", str(config.HTTP_PORT))
        point_port = os.getenv("GO_TO_POINT_PORT", "8080")

        self.control_url = f"http://{robot_ip}:{robot_port}/control"
        self.go_to_point_url = f"http://{robot_ip}:{point_port}/go_to_point"

        print(f"[MCP_Dogzilla] Robot API control={self.control_url}")
        print(f"[MCP_Dogzilla] Robot API go_to_point={self.go_to_point_url}")

    def _post(self, url: str, payload: dict) -> bool:
        try:
            resp = requests.post(url, json=payload, timeout=TIMEOUT)
            if resp.status_code == 200:
                print(f"[MCP_Dogzilla] OK {url} {payload}")
                return True

            print(f"[MCP_Dogzilla] HTTP {resp.status_code} {url} {payload}")
            return False
        except requests.exceptions.ConnectionError:
            print(f"[MCP_Dogzilla] Connection error: {url}")
            return False
        except requests.exceptions.Timeout:
            print(f"[MCP_Dogzilla] Timeout after {TIMEOUT}s: {url}")
            return False
        except Exception as e:
            print(f"[MCP_Dogzilla] Unexpected error: {e}")
            return False

    def dance(self) -> bool:
        return self._post(
            self.control_url,
            {"command": "behavior", "name": "Wave_Body"},
        )

    def _go_to_point(self, point: str) -> bool:
        return self._post(self.go_to_point_url, {"name": point})

    def go_to_point_a(self) -> bool:
        return self._go_to_point("A")

    def go_to_point_b(self) -> bool:
        return self._go_to_point("B")

    def go_to_point_c(self) -> bool:
        return self._go_to_point("C")

    def go_to_point_d(self) -> bool:
        return self._go_to_point("D")


class CommandHandler:
    def __init__(self):
        self.api = RobotAPI()
        self.command_map = {
            52: ("Dancing", self.api.dance),
            19: ("Go to point A", self.api.go_to_point_a),
            20: ("Go to point B", self.api.go_to_point_b),
            21: ("Go to point C", self.api.go_to_point_c),
            22: ("Go to point D", self.api.go_to_point_d),
        }

    def handle(self, cmd: int):
        if cmd in IGNORED_CMDS:
            return
        if cmd in self.command_map:
            label, action = self.command_map[cmd]
            print(f"[MCP_Dogzilla] {label}")
            action()


class MCPDogzillaService:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._speech = None

    def start(self):
        if not getattr(config, "MCP_DOGZILLA_ENABLED", True):
            print("[MCP_Dogzilla] Disabled by config")
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._speech = Speech(
            getattr(config, "MCP_DOGZILLA_SPEECH_PORT", "/dev/ttyUSB0"),
            getattr(config, "MCP_DOGZILLA_SPEECH_BAUD", 115200),
            getattr(config, "MCP_DOGZILLA_DEBUG", True),
        )
        if self._speech.ser is None:
            print("[MCP_Dogzilla] Service not started because speech serial is unavailable")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="mcp_dogzilla_voice_loop",
        )
        self._thread.start()
        print("[MCP_Dogzilla] Voice command service started")

    def stop(self):
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._speech is not None:
            self._speech.close()
        self._thread = None
        self._speech = None

    def _run(self):
        handler = CommandHandler()
        speech = self._speech

        while not self._stop_event.is_set():
            cmd = speech.speech_read()
            if cmd != 999 and cmd in handler.command_map:
                print(f"[MCP_Dogzilla] Detected cmd: {cmd}")
                speech.void_write(cmd)
                handler.handle(cmd)
            else:
                time.sleep(0.01)


mcp_dogzilla_service = MCPDogzillaService()

# -*- coding: utf-8 -*-
import math
import os
import threading
import time
from urllib.parse import urlencode

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
        self.point_base_url = f"http://{robot_ip}:{point_port}"
        self.go_to_point_url = f"http://{robot_ip}:{point_port}/go_to_point"
        self.points_url = f"{self.point_base_url}/points"
        self.set_goal_pose_url = f"{self.point_base_url}/set_goal_pose"
        self.qr_standoff_m = float(os.getenv("GO_TO_POINT_STANDOFF_M", "0.35"))

        print(f"[MCP_Dogzilla] Robot API control={self.control_url}")
        print(f"[MCP_Dogzilla] Robot API go_to_point={self.go_to_point_url}")
        print(f"[MCP_Dogzilla] Robot API set_goal_pose={self.set_goal_pose_url}")

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

    def _get_points(self) -> dict:
        try:
            resp = requests.get(self.points_url, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[MCP_Dogzilla] Get points failed: {e}")
            return {}

    def _send_goal_pose(self, x: float, y: float, yaw: float) -> bool:
        try:
            query = urlencode({"x": x, "y": y, "yaw": yaw})
            url = f"{self.set_goal_pose_url}?{query}"
            resp = requests.get(url, timeout=TIMEOUT)
            if resp.status_code == 200:
                print(f"[MCP_Dogzilla] OK {url}")
                return True
            print(f"[MCP_Dogzilla] HTTP {resp.status_code} {url}")
            return False
        except requests.exceptions.ConnectionError:
            print(f"[MCP_Dogzilla] Connection error: {self.set_goal_pose_url}")
            return False
        except requests.exceptions.Timeout:
            print(f"[MCP_Dogzilla] Timeout after {TIMEOUT}s: {self.set_goal_pose_url}")
            return False
        except Exception as e:
            print(f"[MCP_Dogzilla] Set goal pose failed: {e}")
            return False

    def dance(self) -> bool:
        return self._post(
            self.control_url,
            {"command": "behavior", "name": "Wave_Body"},
        )

    def _go_to_point(self, point: str) -> bool:
        points = self._get_points()
        point_info = points.get(point) or points.get(point.upper()) or points.get(point.lower())
        if not point_info:
            print(f"[MCP_Dogzilla] Point not found: {point}")
            return False

        try:
            point_x = float(point_info["x"])
            point_y = float(point_info["y"])
            approach_yaw = float(point_info.get("yaw", 0.0))
            target_x = point_x - (self.qr_standoff_m * math.cos(approach_yaw))
            target_y = point_y - (self.qr_standoff_m * math.sin(approach_yaw))
            target_yaw = math.atan2(point_y - target_y, point_x - target_x)
        except Exception as e:
            print(f"[MCP_Dogzilla] Invalid point {point}: {e}")
            return False

        print(
            "[MCP_Dogzilla] Voice goal "
            f"{point}: source=({point_x:.2f},{point_y:.2f},{approach_yaw:.2f}) "
            f"target=({target_x:.2f},{target_y:.2f},{target_yaw:.2f}) "
            f"standoff={self.qr_standoff_m:.2f}m"
        )
        return self._send_goal_pose(target_x, target_y, target_yaw)

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

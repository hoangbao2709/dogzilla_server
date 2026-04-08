# -*- coding: utf-8 -*-

from typing import Optional, Dict, Any
import threading
import time  # used by joystick reconnect loop
from . import config

from DOGZILLALib import DOGZILLA as _DOG
from .joystick_dogzilla import Dogzilla_Joystick



class Robot:
    """DOGZILLA wrapper for motion, Z, and attitude with server-side clamp/state."""

    def __init__(self) -> None:
        self.dog: Optional[_DOG] = None

        # locks
        self._z_lock = threading.Lock()
        self._att_lock = threading.Lock()
        self._body_lock = threading.Lock()

        # server-side state
        self._current_z     = int(config.Z_DEFAULT)
        self._roll_current  = float(config.ROLL_DEFAULT)
        self._pitch_current = float(config.PITCH_DEFAULT)
        self._yaw_current   = float(config.YAW_DEFAULT)

        self._body_offset: Dict[str, float] = {
            "tx": 0.0,
            "ty": 0.0,
            "tz": 0.0,
            "rx": 0.0,
            "ry": 0.0,
            "rz": 0.0,
        }

        # joystick state
        self._joystick_thread: Optional[threading.Thread] = None

        if _DOG is not None:
            try:
                self.dog = _DOG(
                    port=config.DOG_PORT,
                    baud=config.DOG_BAUD,
                    verbose=False,
                )
                print(f"[DOGZILLA] Connected on {config.DOG_PORT} @ {config.DOG_BAUD}")
            except Exception as e:
                print("[DOGZILLA] Init error:", e)
                self.dog = None
        else:
            print("[DOGZILLA] Library not found. Running without robot.")

    # ---------- utils ----------

    def _clamp(self, v: float, lo: float, hi: float) -> float:
        return lo if v < lo else hi if v > hi else v

    # ---------- motion ----------

    def resolve_value(self, *, step: Optional[int], speed: Optional[int], is_turn: bool) -> int:
        if speed is not None:
            val = int(speed)
            return int(self._clamp(val, config.TURN_MIN, config.TURN_MAX)) if is_turn else val

        if step is not None:
            return int(step)

        return config.STEP_DEFAULT

    def do_motion(self, cmd: str, *, step: Optional[int] = None, speed: Optional[int] = None) -> str:
        if self.dog is None:
            return "robot not connected"

        is_turn = cmd in ("turnleft", "turnright")
        val = self.resolve_value(step=step, speed=speed, is_turn=is_turn)

        try:
            if cmd == "forward":
                self.dog.forward(int(val))
            elif cmd == "back":
                self.dog.back(int(val))
            elif cmd == "left":
                self.dog.left(int(val))
            elif cmd == "right":
                self.dog.right(int(val))
            elif cmd == "turnleft":
                self.dog.turnleft(int(val))
            elif cmd == "turnright":
                self.dog.turnright(int(val))
            elif cmd == "stop":
                self.dog.stop()
            else:
                return f"unknown command: {cmd}"
        except Exception as e:
            return f"error: {e}"

        if cmd == "stop":
            return "ok: stop"
        if is_turn:
            return f"ok: {cmd}(speed={val})"
        return f"ok: {cmd}({val})"

    # ---------- Z ----------

    def setz(self, z: int) -> str:
        z = int(self._clamp(int(z), config.Z_MIN, config.Z_MAX))

        if self.dog is None:
            with self._z_lock:
                self._current_z = z
            return f"ok: setz({z}) (robot not connected)"

        try:
            if hasattr(self.dog, 'translation'):
                self.dog.translation('z', int(z))
            elif hasattr(self.dog, 'setz'):
                self.dog.setz(int(z))
            else:
                return "error: setz unsupported by DOGZILLA lib"

            with self._z_lock:
                self._current_z = z

            return f"ok: setz({z})"
        except Exception as e:
            return f"error: {e}"

    def adjustz(self, delta: int) -> str:
        with self._z_lock:
            target = self._current_z + int(delta)
        return self.setz(target)

    def z_current(self) -> int:
        with self._z_lock:
            return self._current_z

    # ---------- Attitude ----------

    def _set_axis(self, ax: str, val: float) -> str:
        """Call the expected signature: dog.attitude(axis, value)."""
        if self.dog is None:
            with self._att_lock:
                if ax == 'r':
                    self._roll_current = val
                elif ax == 'p':
                    self._pitch_current = val
                elif ax == 'y':
                    self._yaw_current = val
            return f"ok: attitude({ax}={val}) (robot not connected)"

        try:
            if hasattr(self.dog, "attitude"):
                self.dog.attitude(ax, int(val))  # cast to int for compatibility
            elif ax == 'r' and hasattr(self.dog, "setroll"):
                self.dog.setroll(int(val))
            elif ax == 'p' and hasattr(self.dog, "setpitch"):
                self.dog.setpitch(int(val))
            elif ax == 'y' and hasattr(self.dog, "setyaw"):
                self.dog.setyaw(int(val))
            else:
                return "error: attitude unsupported by DOGZILLA lib"

            with self._att_lock:
                if ax == 'r':
                    self._roll_current = val
                elif ax == 'p':
                    self._pitch_current = val
                else:
                    self._yaw_current = val

            return f"ok: attitude({ax}={val})"
        except Exception as e:
            return f"error: {e}"

    def set_attitude(self, axis: str, value: float) -> str:
        ax = str(axis).lower()[:1]
        if ax not in ('r', 'p', 'y'):
            return "error: invalid axis"

        if ax == 'r':
            v = self._clamp(float(value), config.ROLL_MIN,  config.ROLL_MAX)
        elif ax == 'p':
            v = self._clamp(float(value), config.PITCH_MIN, config.PITCH_MAX)
        else:
            v = self._clamp(float(value), config.YAW_MIN,   config.YAW_MAX)

        return self._set_axis(ax, v)

    # convenience

    def set_roll(self, v: float) -> str:
        return self.set_attitude('r', v)

    def set_pitch(self, v: float) -> str:
        return self.set_attitude('p', v)

    def set_yaw(self, v: float) -> str:
        return self.set_attitude('y', v)

    # status readers

    def roll_current(self) -> float:
        with self._att_lock:
            return self._roll_current

    def pitch_current(self) -> float:
        with self._att_lock:
            return self._pitch_current

    def yaw_current(self) -> float:
        with self._att_lock:
            return self._yaw_current

    # ---------- Body offset (6 slider) ----------

    def set_body_offset(self, tx: float, ty: float, tz: float,
                        rx: float, ry: float, rz: float) -> None:
        """
        Update body_offset state on the server from raw slider values.
        """
        with self._body_lock:
            self._body_offset = {
                "tx": float(tx),
                "ty": float(ty),
                "tz": float(tz),
                "rx": float(rx),
                "ry": float(ry),
                "rz": float(rz),
            }

    def body_offset(self) -> Dict[str, float]:
        """
        Return current body_offset for /status synchronization.
        """
        with self._body_lock:
            return dict(self._body_offset)

    def body_adjust(self, payload: Dict[str, Any]) -> str:
        tx = float(payload.get("tx", 0.0))
        ty = float(payload.get("ty", 0.0))
        tz = float(payload.get("tz", 0.0))
        rx = float(payload.get("rx", 0.0))
        ry = float(payload.get("ry", 0.0))
        rz = float(payload.get("rz", 0.0))

        self.set_body_offset(tx, ty, tz, rx, ry, rz)

        # Keep Z behavior as before.
        try:
            z_min = getattr(config, "Z_MIN", 75)
            z_max = getattr(config, "Z_MAX", 115)
            z_mid = 0.5 * (z_min + z_max)
            z_norm = max(-100.0, min(100.0, tz)) / 100.0
            z_target = z_mid + z_norm * (z_max - z_mid)
            self.setz(int(z_target))
        except Exception as e:
            return f"error: body_adjust/setz failed: {e}"

        # Ranges
        roll_min = getattr(config, "ROLL_MIN", -20.0)
        roll_max = getattr(config, "ROLL_MAX",  20.0)
        pitch_min = getattr(config, "PITCH_MIN", -22.0)
        pitch_max = getattr(config, "PITCH_MAX",  22.0)
        yaw_min = getattr(config, "YAW_MIN", -16.0)
        yaw_max = getattr(config, "YAW_MAX",  16.0)

        def lerp_slider(v: float, lo: float, hi: float) -> float:
            v = max(-100.0, min(100.0, v)) / 100.0  # [-1,1]
            mid = 0.5 * (lo + hi)
            return mid + v * (hi - mid)

        try:
            # Blend translation X/Y into roll/pitch so all sliders affect posture.
            roll_input = rx + ty * 0.5   # Y influences roll.
            pitch_input = ry + tx * 0.5  # X influences pitch.

            roll_target = lerp_slider(roll_input, roll_min, roll_max)
            pitch_target = lerp_slider(pitch_input, pitch_min, pitch_max)
            yaw_target = lerp_slider(rz, yaw_min, yaw_max)

            self.set_roll(roll_target)
            self.set_pitch(pitch_target)
            self.set_yaw(yaw_target)
        except Exception as e:
            return f"error: body_adjust/attitude failed: {e}"

        return "ok: body_adjust applied"

    # ---------- Joystick (USB gamepad) ----------

    def _joystick_loop(self, debug: bool = False, js_id: int = 0) -> None:
        """
        Read USB joystick events and forward them to Dogzilla_Joystick.
        Runs in a dedicated daemon thread.
        """
        if self.dog is None:
            return

        js = Dogzilla_Joystick(self.dog, js_id=js_id, debug=debug)

        # if not js.is_Opened():
        #     print("[Robot] joystick: failed to open device")
        #     return

        while True:
            state = js.joystick_handle()
            if state != js.STATE_OK:
                if state == js.STATE_KEY_BREAK:
                    break
                time.sleep(1.0)
                js.reconnect()

    def start_joystick(self, debug: bool = False, js_id: int = 0) -> None:
        """
        Call this during app startup to launch the joystick thread.
        """
        if self.dog is None:
            return

        if self._joystick_thread is not None and self._joystick_thread.is_alive():
            return

        self._joystick_thread = threading.Thread(
            target=self._joystick_loop,
            kwargs={"debug": debug, "js_id": js_id},
            daemon=True,
            name="robot_joystick_loop",
        )
        self._joystick_thread.start()


# Global singleton
robot = Robot()

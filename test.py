Dưới đây là các file đã cập nhật/bo sung để server hỗ trợ điều khiển **Attitude\_pitch** khi trục Y (chuột) thay đổi. Mặc định: đưa chuột **về trước (y giảm)** → **giảm** pitch; đưa chuột **về sau (y tăng)** → **tăng** pitch.

> Lưu ý: Mình giữ nguyên API cũ và **bo sung** các lệnh/endpoint mới:
>
> * `POST /control` với `command: setpitch | adjustpitch | mousepitch`
> * Trường `y` của `mousepitch` là số thực chuẩn hoá trong khoảng **\[-1, 1]** (âm = đưa chuột về trước), có thể truyền `gain` tuỳ chọn, nếu không sẽ dùng `PITCH_GAIN` trong config.

---

## 1) `dogzilla_server/config.py`

```python
import os

# HTTP
HTTP_PORT     = int(os.environ.get("HTTP_PORT", "9000"))

# Camera (server side)
CAMERA_INDEX  = int(os.environ.get("CAMERA_INDEX", "0"))
FRAME_W       = int(os.environ.get("CAM_WIDTH", "640"))
FRAME_H       = int(os.environ.get("CAM_HEIGHT", "480"))
FRAME_FPS     = int(os.environ.get("CAM_FPS", "30"))

# Robot serial
DOG_PORT      = os.environ.get("DOGZILLA_PORT", "/dev/ttyAMA0")
DOG_BAUD      = int(os.environ.get("DOGZILLA_BAUD", "115200"))

# Motion defaults
STEP_DEFAULT  = int(os.environ.get("STEP_DEFAULT", "8"))
TURN_MIN      = int(os.environ.get("TURN_MIN", "-70"))
TURN_MAX      = int(os.environ.get("TURN_MAX", "70"))

# Z height (setz / adjustz)
Z_MIN         = int(os.environ.get("Z_MIN", "75"))
Z_MAX         = int(os.environ.get("Z_MAX", "110"))
Z_DEFAULT     = int(os.environ.get("Z_DEFAULT", "105"))

# Pitch (attitude) – bo sung
PITCH_MIN     = int(os.environ.get("PITCH_MIN", "-30"))    # độ
PITCH_MAX     = int(os.environ.get("PITCH_MAX", "30"))     # độ
PITCH_DEFAULT = int(os.environ.get("PITCH_DEFAULT", "0"))  # độ
PITCH_GAIN    = float(os.environ.get("PITCH_GAIN", "20"))  # độ cho y=±1 (mousepitch)
```

---

## 2) `dogzilla_server/robot.py`

```python
from typing import Optional
import threading
from . import config

try:
    from DOGZILLALib import DOGZILLA as _DOG
except Exception:
    try:
        from dogzilla import DOGZILLA as _DOG
    except Exception as _e:
        _DOG = None
        print("[Robot] Cannot import DOGZILLA class:", _e)


class Robot:
    """Wrapper around DOGZILLA với fallback an toàn + tracking Z/Pitch phía server."""

    def __init__(self) -> None:
        self.dog = None
        self._z_lock = threading.Lock()
        self._pitch_lock = threading.Lock()
        self._current_z = config.Z_DEFAULT
        self._current_pitch = config.PITCH_DEFAULT
        if _DOG is not None:
            try:
                self.dog = _DOG(port=config.DOG_PORT, baud=config.DOG_BAUD, verbose=False)
                print(f"[DOGZILLA] Connected on {config.DOG_PORT} @ {config.DOG_BAUD}")
            except Exception as e:
                print("[DOGZILLA] Init error:", e)
                self.dog = None
        else:
            print("[DOGZILLA] Library not found. Running without robot.")

    # ----- utils -----
    def _clamp(self, v: float, lo: float, hi: float) -> float:
        return lo if v < lo else hi if v > hi else v

    # ----- motion -----
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
                self.dog.forward(val)
            elif cmd == "back":
                self.dog.back(val)
            elif cmd == "left":
                self.dog.left(val)
            elif cmd == "right":
                self.dog.right(val)
            elif cmd == "turnleft":
                self.dog.turnleft(val)
            elif cmd == "turnright":
                self.dog.turnright(val)
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

    # ----- Z height -----
    def setz(self, z: int) -> str:
        z = int(self._clamp(int(z), config.Z_MIN, config.Z_MAX))
        if self.dog is None:
            with self._z_lock:
                self._current_z = z
            return f"ok: setz({z}) (robot not connected)"
        try:
            if hasattr(self.dog, 'translation'):
                self.dog.translation('z', z)
            elif hasattr(self.dog, 'setz') and callable(getattr(self.dog, 'setz')):
                self.dog.setz(z)
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

    # ----- Pitch (attitude) -----
    def set_pitch(self, pitch_deg: float) -> str:
        p = self._clamp(float(pitch_deg), config.PITCH_MIN, config.PITCH_MAX)
        if self.dog is None:
            with self._pitch_lock:
                self._current_pitch = p
            return f"ok: setpitch({p}) (robot not connected)"
        try:
            # Ưu tiên API có tham số pitch rõ ràng
            if hasattr(self.dog, 'attitude'):
                # Giả định: dog.attitude(pitch=deg) tồn tại
                try:
                    self.dog.attitude(pitch=p)
                except TypeError:
                    # Một số lib có thể dùng tuple hoặc trật tự khác
                    self.dog.attitude(0, p, 0)
            elif hasattr(self.dog, 'set_pitch') and callable(getattr(self.dog, 'set_pitch')):
                self.dog.set_pitch(p)
            elif hasattr(self.dog, 'rotation') and callable(getattr(self.dog, 'rotation')):
                # Giả định: rotation('pitch', deg)
                self.dog.rotation('pitch', p)
            else:
                return "error: pitch unsupported by DOGZILLA lib"
            with self._pitch_lock:
                self._current_pitch = p
            return f"ok: setpitch({p})"
        except Exception as e:
            return f"error: {e}"

    def adjust_pitch(self, delta_deg: float) -> str:
        with self._pitch_lock:
            target = self._current_pitch + float(delta_deg)
        return self.set_pitch(target)

    def pitch_current(self) -> float:
        with self._pitch_lock:
            return self._current_pitch


# Global singleton robot instance
robot = Robot()
```

---

## 3) `dogzilla_server/routes/control.py`

```python
from flask import Blueprint, request
from ..robot import robot
from .. import config

bp = Blueprint("control", __name__)

@bp.route("/control", methods=["POST"])
def control():
    data = request.get_json(silent=True) or {}
    cmd    = str(data.get("command", "")).lower().strip()

    raw_step   = data.get("step")
    raw_speed  = data.get("speed")
    raw_value  = data.get("value")   # setz / setpitch
    raw_delta  = data.get("delta")   # adjustz / adjustpitch

    # numeric parsing
    step = None
    if raw_step is not None:
        try:
            step = int(raw_step)
        except Exception:
            return ("invalid step", 400, {"Content-Type": "text/plain; charset=utf-8"})

    speed = None
    if raw_speed is not None:
        try:
            speed = int(raw_speed)
        except Exception:
            return ("invalid speed", 400, {"Content-Type": "text/plain; charset=utf-8"})

    # dispatch
    if cmd in ("forward", "back", "left", "right", "turnleft", "turnright", "stop"):
        res = robot.do_motion(cmd, step=step, speed=speed)

    elif cmd == "setz":
        if raw_value is None:
            return ("missing value", 400, {"Content-Type": "text/plain; charset=utf-8"})
        res = robot.setz(raw_value)

    elif cmd == "adjustz":
        if raw_delta is None:
            return ("missing delta", 400, {"Content-Type": "text/plain; charset=utf-8"})
        res = robot.adjustz(raw_delta)

    # ---- NEW: pitch ----
    elif cmd == "setpitch":
        if raw_value is None:
            return ("missing value", 400, {"Content-Type": "text/plain; charset=utf-8"})
        try:
            val = float(raw_value)
        except Exception:
            return ("invalid value", 400, {"Content-Type": "text/plain; charset=utf-8"})
        res = robot.set_pitch(val)

    elif cmd == "adjustpitch":
        if raw_delta is None:
            return ("missing delta", 400, {"Content-Type": "text/plain; charset=utf-8"})
        try:
            d = float(raw_delta)
        except Exception:
            return ("invalid delta", 400, {"Content-Type": "text/plain; charset=utf-8"})
        res = robot.adjust_pitch(d)

    # ---- NEW: mousepitch (y ∈ [-1, 1]) ----
    elif cmd == "mousepitch":
        if "y" not in data:
            return ("missing y", 400, {"Content-Type": "text/plain; charset=utf-8"})
        try:
            y = float(data.get("y"))  # y âm = chuột đẩy về trước
        except Exception:
            return ("invalid y", 400, {"Content-Type": "text/plain; charset=utf-8"})
        gain = float(data.get("gain", config.PITCH_GAIN))
        # Quy ước: y âm (về trước) -> giảm pitch (dấu -)
        target = config.PITCH_DEFAULT + (-gain * y)
        res = robot.set_pitch(target)

    elif cmd == "status":
        from .status import status as status_route
        return status_route()

    else:
        return (f"unknown command: {cmd}", 400, {"Content-Type": "text/plain; charset=utf-8"})

    if isinstance(res, str) and res.startswith("ok"):
        return (res, 200, {"Content-Type": "text/plain; charset=utf-8"})
    else:
        return (res, 400, {"Content-Type": "text/plain; charset=utf-8"})
```

---

## 4) `dogzilla_server/routes/status.py`

```python
from flask import Blueprint, jsonify
from .. import config
from ..robot import robot

bp = Blueprint("status", __name__)

@bp.route("/status", methods=["GET", "POST"])
def status():
    s = {
        "robot_connected": robot.dog is not None,
        "turn_speed_range": [config.TURN_MIN, config.TURN_MAX],
        "step_default": config.STEP_DEFAULT,
        "z_range": [config.Z_MIN, config.Z_MAX],
        "z_current": robot.z_current(),
        # NEW: pitch info
        "pitch_range": [config.PITCH_MIN, config.PITCH_MAX],
        "pitch_current": robot.pitch_current(),
    }
    if robot.dog is not None:
        try:
            s["battery"] = robot.dog.read_battery()
        except Exception:
            s["battery"] = None
        try:
            s["fw"] = robot.dog.read_version()
        except Exception:
            s["fw"] = None
    return jsonify(s)
```

---

## 5) Ví dụ gọi API

* Điều chỉnh tuyệt đối pitch:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"command":"setpitch","value":-10}' \
  http://<pi-ip>:9000/control
```

* Điều chỉnh tương đối pitch:

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"command":"adjustpitch","delta":5}' \
  http://<pi-ip>:9000/control
```

* Điều khiển theo trục Y của chuột (chuẩn hoá y∈\[-1,1]):

```bash
# y = -1 (đẩy hết cỡ về trước) -> giảm pitch tối đa theo gain
curl -X POST -H "Content-Type: application/json" \
  -d '{"command":"mousepitch","y":-0.35}' \
  http://<pi-ip>:9000/control

# có thể truyền gain tuỳ ý (độ trên mỗi đơn vị y)
curl -X POST -H "Content-Type: application/json" \
  -d '{"command":"mousepitch","y":0.2, "gain":25}' \
  http://<pi-ip>:9000/control
```

---

### Ghi chú tích hợp frontend (tuỳ chọn)

Trên web UI, bạn lấy `mouseY` rồi chuẩn hoá về \[-1,1], ví dụ:

```js
const normY = (y, h) => ((y / h) - 0.5) * 2; // y=0 top -> -1; y=h bottom -> +1
async function sendMousePitch(normY) {
  await fetch('/control', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command: 'mousepitch', y: normY })
  });
}
```

Nếu bạn muốn mình chuyển toàn bộ server trả về JSON thay vì text/plain, hoặc thêm auth token, mình sẽ cập nhật ngay trong phiên bản tiếp theo.

# dogzilla_server/routes/control.py
# -*- coding: utf-8 -*-
from flask import Blueprint, request, jsonify
from ..robot import robot
import json
from .. import config
import os
import signal
import shlex
import subprocess
import time
bp = Blueprint("control", __name__)
LIDAR_CONTAINER = os.environ.get("DOGZILLA_LIDAR_CONTAINER", "yahboom_humble")
MAP_SAVE_DIR = os.environ.get("DOGZILLA_MAP_SAVE_DIR", "/root/docker-mi/saved_maps")
DEFAULT_NAV_MAP_PATH = (os.environ.get("DOGZILLA_DEFAULT_NAV_MAP", "") or "").strip() or None
SUPPORTED_LIDAR_MODES = ( "navigation", "live_slam")
LIDAR_PROCESS_PATTERNS = (
    "robot_navigation_static.launch.py",
    "robot_navigation.launch.py",
    "cartographer_node",
    "amcl",
    "map_server",
    "planner_server",
    "controller_server",
    "behavior_server",
    "bt_navigator",
    "waypoint_follower",
    "velocity_smoother",
    "lifecycle_manager",
    "oradar_scan",
)


def _ok(result: str = "ok"):
    return jsonify({"ok": True, "result": result}), 200


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


def _run_checked(cmd, *, timeout=None):
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        check=True,
    )


def _tail_in_container(container: str, path: str, lines: int = 40) -> str:
    try:
        res = subprocess.run(
            [
                "docker",
                "exec",
                container,
                "bash",
                "-lc",
                f"tail -n {int(lines)} {path} 2>/dev/null || true",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return (res.stdout or "").strip()
    except Exception:
        return ""


def _nav_web_process_running() -> bool:
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                LIDAR_CONTAINER,
                "bash",
                "-lc",
                "ps -eo args | grep -F '/root/docker-mi/main.py' | grep -v grep >/dev/null",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _lidar_process_running() -> bool:
    try:
        pattern_expr = "|".join(LIDAR_PROCESS_PATTERNS)
        result = subprocess.run(
            [
                "docker",
                "exec",
                LIDAR_CONTAINER,
                "bash",
                "-lc",
                (
                    "ps -eo args | grep -E "
                    f"\"{pattern_expr}\" | grep -v grep >/dev/null"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _nav_state_snapshot() -> dict | None:
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                LIDAR_CONTAINER,
                "bash",
                "-lc",
                "python3 - <<'PY'\n"
                "import json, sys, urllib.request\n"
                "try:\n"
                "    with urllib.request.urlopen('http://127.0.0.1:8080/state', timeout=1.5) as r:\n"
                "        print(r.read().decode('utf-8'))\n"
                "except Exception:\n"
                "    sys.exit(1)\n"
                "PY",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return None
        raw = (result.stdout or "").strip()
        if not raw:
            return None
        return json.loads(raw)
    except Exception:
        return None


def _lidar_running() -> bool:
    state = _nav_state_snapshot() or {}
    status = state.get("status") or {}
    if any(
        bool(status.get(key))
        for key in ("slam_ok", "tf_ok", "nav2_server_ok", "nav2_goal_active")
    ):
        return True
    return _lidar_process_running()


def _detect_lidar_mode() -> str | None:
    try:
        checks = (
            ("navigation", "ps -eo args | grep -E \"robot_navigation_static.launch.py|amcl|map_server\" | grep -v grep >/dev/null"),
            ("live_slam", "ps -eo args | grep -E \"robot_navigation.launch.py|cartographer_node\" | grep -v grep >/dev/null"),
        )
        for mode, cmd in checks:
            result = subprocess.run(
                ["docker", "exec", LIDAR_CONTAINER, "bash", "-lc", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                return mode
    except Exception:
        return None
    return None


def _resolve_navigation_map_path(map_name: str | None, map_path: str | None) -> str:
    raw_map_path = (map_path or "").strip()
    if raw_map_path:
        if not raw_map_path.startswith("/"):
            raise ValueError("navigation map_path must be an absolute .yaml path inside container")
        if not raw_map_path.endswith((".yaml", ".yml")):
            raise ValueError("navigation map_path must point to a .yaml file")
        return raw_map_path

    safe_name = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in (map_name or "").strip())
    if not safe_name:
        if DEFAULT_NAV_MAP_PATH:
            return DEFAULT_NAV_MAP_PATH

        latest_map_path = _find_latest_saved_map_path()
        if latest_map_path:
            return latest_map_path

        raise ValueError("navigation requires map_name, map_path, or at least one saved .yaml map in the container")
    return os.path.join(MAP_SAVE_DIR, safe_name + ".yaml")


def _find_latest_saved_map_path() -> str | None:
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                LIDAR_CONTAINER,
                "bash",
                "-lc",
                (
                    "python3 - <<'PY'\n"
                    "from pathlib import Path\n"
                    "map_dir = Path(" + repr(MAP_SAVE_DIR) + ")\n"
                    "candidates = [p for p in map_dir.glob('*.yaml') if p.is_file()]\n"
                    "if not candidates:\n"
                    "    raise SystemExit(1)\n"
                    "latest = max(candidates, key=lambda p: p.stat().st_mtime)\n"
                    "print(str(latest))\n"
                    "PY"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            latest = (result.stdout or "").strip()
            return latest or None
    except Exception:
        return None
    return None


def _check_launch_runtime_ready(mode: str) -> tuple[bool, str]:
    if mode not in SUPPORTED_LIDAR_MODES:
        return False, f"unsupported lidar mode: {mode}"

    if mode == "navigation":
        launch_name = "robot_navigation_static.launch.py"
    else:
        launch_name = "robot_navigation.launch.py"
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                LIDAR_CONTAINER,
                "bash",
                "-lc",
                (
                    "python3 - <<'PY'\n"
                    "from pathlib import Path\n"
                    "\n"
                    f"launch_path = Path('/root/yahboomcar_ws/install/mi_bringup/share/mi_bringup/launch/{launch_name}')\n"
                    "\n"
                    "if not launch_path.exists():\n"
                    "    print('missing installed launch: ' + str(launch_path))\n"
                    "    raise SystemExit(2)\n"
                    "\n"
                    f"print('{mode} runtime ready')\n"
                    "PY"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except Exception as e:
        return False, f"runtime check failed: {e}"

    details = (result.stdout or "").strip() or (result.stderr or "").strip()
    if result.returncode == 0:
        return True, details or f"{mode} runtime ready"

    return (
        False,
        "stale mi_bringup install inside container; rebuild and re-source the ROS workspace"
        + (f" | {details}" if details else ""),
    )


def _ensure_nav_web_process_running() -> None:
    if _nav_web_process_running():
        return

    _run_checked(
        [
            "docker",
            "exec",
            "-d",
            LIDAR_CONTAINER,
            "bash",
            "-lc",
            "source /opt/ros/humble/setup.bash && "
            "source /root/yahboomcar_ws/install/setup.bash && "
            "python3 /root/docker-mi/main.py "
            "> /tmp/lidar_map.log 2>&1",
        ],
    )


def _request_nav_web(path: str) -> bool:
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                LIDAR_CONTAINER,
                "bash",
                "-lc",
                (
                    "python3 - <<'PY'\n"
                    "import sys, urllib.request\n"
                    f"url = 'http://127.0.0.1:8080{path}'\n"
                    "try:\n"
                    "    with urllib.request.urlopen(url, timeout=2.0) as r:\n"
                    "        sys.exit(0 if 200 <= int(getattr(r, 'status', 0)) < 300 else 1)\n"
                    "except Exception:\n"
                    "    sys.exit(1)\n"
                    "PY"
                ),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


POSTURE_ACTIONS = {
    "Lie_Down": 1,
    "Stand_Up": 2,
    "Crawl": 3,
    "Squat": 6,
    "Sit_Down": 12,
}

BEHAVIOR_ACTIONS = {
    "Turn_Around": 4,
    "Mark_Time": 5,
    "Turn_Roll": 7,
    "Turn_Pitch": 8,
    "Turn_Yaw": 9,
    "3_Axis": 10,
    "Pee": 11,
    "Wave_Hand": 13,
    "Stretch": 14,
    "Wave_Body": 15,
    "Swing": 16,
    "Pray": 17,
    "Seek": 18,
    "Handshake": 19,
}
# ===== FIX ROS2 HARD RESET =====
def _ros2_hard_reset(container: str):
    patterns = [
        "robot_navigation",
        "cartographer",
        "amcl",
        "map_server",
        "planner_server",
        "controller_server",
        "bt_navigator",
        "waypoint_follower",
        "velocity_smoother",
        "lifecycle_manager",
        "/root/docker-mi/main.py",
    ]

    for p in patterns:
        subprocess.run(
            ["docker", "exec", container, "pkill", "-f", p],
            check=False
        )

    subprocess.run(["docker", "exec", container, "pkill", "-f", "ros2"], check=False)

    subprocess.run(["docker", "exec", container, "bash", "-lc", "rm -rf /dev/shm/* || true"], check=False)
    subprocess.run(["docker", "exec", container, "bash", "-lc", "ros2 daemon stop || true; ros2 daemon start || true"], check=False)

    time.sleep(2)


# ===== WAIT NAV2 READY =====
def _wait_nav2_active(container: str, timeout=15):
    for _ in range(timeout):
        res = subprocess.run(
            [
                "docker","exec",container,"bash","-lc",
                "source /opt/ros/humble/setup.bash && "
                "source /root/yahboomcar_ws/install/setup.bash && "
                "ros2 lifecycle get /controller_server 2>/dev/null || true"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if "active [3]" in (res.stdout or ""):
            return True
        time.sleep(1)
    return False

@bp.route("/control", methods=["POST"])
def control():
    data = request.get_json(silent=True) or {}
    cmd = (data.get("command") or "").strip().lower()
    if not cmd:
        return _err("missing 'command' field")

    raw_value = data.get("value")
    raw_delta = data.get("delta")

    # ---------- 1) Motion + stop ----------
    if cmd in ("forward", "back", "left", "right", "turnleft", "turnright", "stop"):
        step = data.get("step")
        speed = data.get("speed")
        mode = data.get("mode")
        res = robot.do_motion(cmd, step=step, speed=speed, mode=mode)
        print("[BODY_ADJUST] payload =", res)
        if res.startswith("error"):
            return _err(res, 500)
        return _ok(res)

    if cmd in ("speed_mode", "pace"):
        mode = data.get("mode")
        if not mode:
            return _err("speed_mode requires 'mode' = 'slow'|'normal'|'high'")

        res = robot.set_speed_mode(mode)
        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    if cmd in ("setz", "set_z"):
        if raw_value is None:
            return _err("setz requires 'value'")
        try:
            res = robot.setz(int(raw_value))
        except Exception:
            return _err("setz requires integer 'value'")
        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    if cmd in ("adjustz", "adjust_z"):
        if raw_delta is None:
            return _err("adjustz requires 'delta'")
        try:
            res = robot.adjustz(int(raw_delta))
        except Exception:
            return _err("adjustz requires integer 'delta'")
        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    if cmd in ("setroll", "setpitch", "setyaw"):
        if raw_value is None:
            return _err(f"{cmd} requires 'value'")
        try:
            value = float(raw_value)
        except Exception:
            return _err(f"{cmd} requires numeric 'value'")

        if cmd == "setroll":
            res = robot.set_roll(value)
        elif cmd == "setpitch":
            res = robot.set_pitch(value)
        else:
            res = robot.set_yaw(value)

        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    if cmd in ("adjustroll", "adjustpitch", "adjustyaw"):
        if raw_delta is None:
            return _err(f"{cmd} requires 'delta'")
        try:
            delta = float(raw_delta)
        except Exception:
            return _err(f"{cmd} requires numeric 'delta'")

        if cmd == "adjustroll":
            res = robot.adjust_roll(delta)
        elif cmd == "adjustpitch":
            res = robot.adjust_pitch(delta)
        else:
            res = robot.adjust_yaw(delta)

        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    if cmd == "gait_type":
        mode = (data.get("mode") or "").strip().lower()
        if not mode:
            return _err("gait_type requires 'mode' = 'trot'|'walk'|'high_walk'")
        res = robot.set_gait_type(mode)
        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    if cmd == "perform":
        action = (data.get("action") or "").strip().lower()
        if action not in ("on", "off"):
            return _err("perform requires 'action' = 'on'|'off'")
        res = robot.set_perform(action == "on")
        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    if cmd == "mark_time":
        if raw_value is None:
            return _err("mark_time requires 'value'")
        try:
            res = robot.set_mark_time(int(raw_value))
        except Exception:
            return _err("mark_time requires integer 'value'")
        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    if cmd == "reset":
        res = robot.reset_pose()
        if res.startswith("error"):
            return _err(res, 400)
        return _ok(res)

    # ---------- 2) Posture ----------
    if cmd == "posture":
        name = data.get("name")
        if not name:
            return _err("posture requires 'name'")
        action_id = POSTURE_ACTIONS.get(name)
        if action_id is None:
            return _err(f"unknown posture: {name}")
        if robot.dog is None or not hasattr(robot.dog, "action"):
            return _err("robot not connected or action() unsupported", 500)
        try:
            robot.dog.action(action_id)
            return _ok(f"posture {name} -> action({action_id})")
        except Exception as e:
            return _err(str(e), 500)

    # ---------- 3) Behavior (fun + axis motion) ----------
    if cmd == "behavior":
        name = data.get("name")
        if not name:
            return _err("behavior requires 'name'")
        action_id = BEHAVIOR_ACTIONS.get(name)
        if action_id is None:
            return _err(f"unknown behavior: {name}")
        if robot.dog is None or not hasattr(robot.dog, "action"):
            return _err("robot not connected or action() unsupported", 500)
        try:
            robot.dog.action(action_id)
            return _ok(f"behavior {name} -> action({action_id})")
        except Exception as e:
            return _err(str(e), 500)

    # ---------- 3.5) Stabilizing / IMU mode ----------
    if cmd == "stabilizing_mode":
        action = (data.get("action") or "").strip().lower()

        if action not in ("on", "off", "toggle"):
            return _err("stabilizing_mode requires 'action' = 'on'|'off'|'toggle'")

        if robot.dog is None or not hasattr(robot.dog, "imu"):
            print("[Control]   WARNING: robot not connected or imu() unsupported -> TEST ONLY, skip imu()")
            return _ok(f"[TEST ONLY] stabilizing_mode({action}) received but dog/imu not ready")

        current = getattr(robot, "stabilizing_enabled", False)

        try:
            if action == "on":
                robot.dog.imu(1)
                robot.stabilizing_enabled = True
                return _ok("stabilizing_mode -> ON (imu(1))")

            if action == "off":
                robot.dog.imu(0)
                robot.stabilizing_enabled = False
                return _ok("stabilizing_mode -> OFF (imu(0))")

            # toggle
            new_state = not current
            robot.dog.imu(1 if new_state else 0)
            robot.stabilizing_enabled = new_state
            return _ok(f"stabilizing_mode toggled -> {'ON' if new_state else 'OFF'}")

        except Exception as e:
            print(f"[Control]   ERROR calling imu(): {e}")
            return _err(str(e), 500)

    if cmd == "lidar":
        action = (data.get("action") or "").strip().lower()

        if action not in ("start", "stop"):
            return _err("lidar requires 'action' = 'start'|'stop'")

        mode = (data.get("mode") or "live_slam").strip().lower()
        if mode not in SUPPORTED_LIDAR_MODES:
            return _err("lidar start requires 'mode' = 'navigation'|'live_slam'")

        container = LIDAR_CONTAINER

        try:
            if action == "stop":
                subprocess.run(["docker", "start", container], check=False)
                _ros2_hard_reset(container)
                return _ok("lidar stopped + ROS2 reset")
            subprocess.run(["docker", "start", container], check=False)
            _ros2_hard_reset(container)
            
            ready, details = _check_launch_runtime_ready(mode)
            if not ready:
                return _err(details, 500)

            resolved_map_path = None
            if mode == "navigation":
                try:
                    resolved_map_path = _resolve_navigation_map_path(
                        data.get("map_name"),
                        data.get("map_path"),
                    )
                except ValueError as e:
                    return _err(str(e))

            if mode == "navigation":
                ros_launch_cmd = (
                    "source /opt/ros/humble/setup.bash && "
                    "source /root/yahboomcar_ws/install/setup.bash && "
                    f"ros2 launch mi_bringup robot_navigation_static.launch.py map:={shlex.quote(resolved_map_path)} "
                    "> /tmp/lidar_ros.log 2>&1"
                )
            else:
                ros_launch_cmd = (
                    "source /opt/ros/humble/setup.bash && "
                    "source /root/yahboomcar_ws/install/setup.bash && "
                    "ros2 launch mi_bringup robot_navigation.launch.py "
                    "> /tmp/lidar_ros.log 2>&1"
                )

            _run_checked([
                "docker", "exec", "-d", container,
                "bash", "-lc", ros_launch_cmd,
            ])

            time.sleep(5)

            if mode == "navigation":
                if not _wait_nav2_active(container):
                    ros_log = _tail_in_container(container, "/tmp/lidar_ros.log")
                    return _err("nav2 not active | " + ros_log, 500)

            _ensure_nav_web_process_running()

            if mode == "live_slam":
                _request_nav_web("/use_live_map")

            extra = f" map={resolved_map_path}" if resolved_map_path else ""
            return _ok(f"lidar start -> {mode}{extra}")

        except Exception as e:
            return _err(str(e), 500)



    # ---------- 5) Body adjust (6 slider) ----------
    if cmd == "body_adjust":
        """
        Frontend gá»­i JSON:
        {
          "tx": ..., "ty": ..., "tz": ...,
          "rx": ..., "ry": ..., "rz": ...
        }

        á» Ä‘Ă¢y ta khĂ´ng map chi tiáº¿t ná»¯a mĂ  giao cho robot.body_adjust()
        trong robot.py xá»­ lĂ½ (clamp + apply xuá»‘ng DOGZILLA náº¿u cĂ³,
        Ä‘á»“ng thá»i lÆ°u state body_offset Ä‘á»ƒ /status dĂ¹ng Ä‘á»“ng bá»™ slider).
        """
        payload = {
            "tx": float(data.get("tx", 0.0)),
            "ty": float(data.get("ty", 0.0)),
            "tz": float(data.get("tz", 0.0)),
            "rx": float(data.get("rx", 0.0)),
            "ry": float(data.get("ry", 0.0)),
            "rz": float(data.get("rz", 0.0)),
        }

        res = robot.body_adjust(payload)
        print("[BODY_ADJUST] payload =", payload)

        if res.startswith("error"):
            return _err(res, 500)
        return _ok(res)

    # ---------- 6) Legacy / status nhanh ----------
    if cmd == "status":
        return jsonify({
            "robot_connected": robot.dog is not None,
            "speed_mode": robot.speed_mode(),
            "gait_type": robot.gait_type(),
            "perform_enabled": robot.perform_enabled(),
            "stabilizing_enabled": getattr(robot, "stabilizing_enabled", False),
            "lidar_running": _lidar_running(),
            "lidar_mode": _detect_lidar_mode(),
            "lidar": {
                "running": _lidar_running(),
                "mode": _detect_lidar_mode(),
            },
            "z_current": robot.z_current(),
            "roll_current": robot.roll_current(),
            "pitch_current": robot.pitch_current(),
            "yaw_current": robot.yaw_current(),
        })

    # ---------- unknown ----------
    return _err(f"unknown command: {cmd}")

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
    "/root/docker-mi/main.py",
    "/root/docker-mi/main_nav.py",
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
    "robot_navigation_static.launch.py",
    "cartographer_occupancy_grid_node",
    "occupancy_grid",
    "slam_live_map_viewer",
)
ROS_REQUIRED_NODES = (
    "/dogzilla_state_bridge",
    "/dogzilla_cmd_adapter",
)
ROS_STACK_NODES = (
    "/cartographer_node",
    "/cartographer_occupancy_grid_node",
    "/planner_server",
    "/controller_server",
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


def _build_static_map_arg(raw_value: object) -> str:
    raw = str(raw_value or "").strip()
    if not raw:
        return ""

    if raw.startswith("map:="):
        raw = raw.split("map:=", 1)[1].strip()

    safe_map_name = os.path.splitext(os.path.basename(raw))[0]
    if not safe_map_name:
        return ""

    return f" map:=/root/docker-mi/saved_maps/{safe_map_name}.pbstream"


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


def _get_ros_nodes_in_container():
    try:
        script = r"""
import sys
import time
import rclpy

try:
    rclpy.init()
    node = rclpy.create_node("dogzilla_node_probe")
    names = set()
    deadline = time.time() + 2.0
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        for name, namespace in node.get_node_names_and_namespaces():
            ns = (namespace or "").rstrip("/")
            full = f"{ns}/{name}" if ns and ns != "/" else f"/{name}"
            names.add(full)
    for item in sorted(names):
        print(item)
    node.destroy_node()
    rclpy.shutdown()
except Exception as exc:
    print(str(exc), file=sys.stderr)
    try:
        if rclpy.ok():
            rclpy.shutdown()
    except Exception:
        pass
    sys.exit(1)
"""
        result = subprocess.run(
            [
                "docker",
                "exec",
                LIDAR_CONTAINER,
                "bash",
                "-lc",
                "source /opt/ros/humble/setup.bash && "
                "source /root/yahboomcar_ws/install/setup.bash && "
                f"python3 - <<'PY'\n{script}\nPY",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return set()
        return {
            line.strip()
            for line in (result.stdout or "").splitlines()
            if line.strip().startswith("/")
        }
    except Exception:
        return set()


def _publish_cmd_vel(vx: float, vy: float, wz: float):
    script = f"""
import sys
import time
import rclpy
from geometry_msgs.msg import Twist

try:
    rclpy.init()
    node = rclpy.create_node("dogzilla_manual_cmd_pub")
    pub = node.create_publisher(Twist, "/cmd_vel", 10)

    msg = Twist()
    msg.linear.x = {float(vx)!r}
    msg.linear.y = {float(vy)!r}
    msg.linear.z = 0.0
    msg.angular.x = 0.0
    msg.angular.y = 0.0
    msg.angular.z = {float(wz)!r}

    deadline = time.time() + 0.5
    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=0.05)

    for _ in range(3):
        pub.publish(msg)
        rclpy.spin_once(node, timeout_sec=0.05)
        time.sleep(0.05)

    node.destroy_node()
    rclpy.shutdown()
except Exception as exc:
    print(str(exc), file=sys.stderr)
    try:
        if rclpy.ok():
            rclpy.shutdown()
    except Exception:
        pass
    sys.exit(1)
"""
    return subprocess.run(
        [
            "docker",
            "exec",
            LIDAR_CONTAINER,
            "bash",
            "-lc",
            "source /opt/ros/humble/setup.bash && "
            "source /root/yahboomcar_ws/install/setup.bash && "
            f"python3 - <<'PY'\n{script}\nPY",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def _lidar_running() -> bool:
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
        if result.returncode == 0:
            nodes = _get_ros_nodes_in_container()
            if (
                all(node in nodes for node in ROS_REQUIRED_NODES)
                and any(node in nodes for node in ROS_STACK_NODES)
            ):
                return True
    except Exception:
        pass
    return False


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
        if _lidar_running():
            vx = 0.0
            vy = 0.0
            wz = 0.0

            if cmd == "forward":
                vx = 0.08
            elif cmd == "back":
                vx = -0.08
            elif cmd == "left":
                vy = 0.06
            elif cmd == "right":
                vy = -0.06
            elif cmd == "turnleft":
                wz = 0.45
            elif cmd == "turnright":
                wz = -0.45
            elif cmd == "stop":
                vx = 0.0
                vy = 0.0
                wz = 0.0

            res = _publish_cmd_vel(vx, vy, wz)

            if res.returncode != 0:
                return _err(res.stderr or res.stdout or "cmd_vel publish failed", 500)

            return _ok(f"ros cmd_vel vx={vx}, vy={vy}, wz={wz}")

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

        container = LIDAR_CONTAINER

        try:
            if action == "start":
                restart_for_static_map = mode == "navigation"
                if _lidar_process_running() and not restart_for_static_map:
                    return _ok(f"lidar process already running ({mode})")
                if _lidar_running() and not restart_for_static_map:
                    return _ok(f"lidar already running ({mode})")
                robot.release_serial()
                subprocess.run(["docker", "start", container], check=False)
                subprocess.run(
                    ["docker", "exec", container, "pkill", "-f", "ros2"],
                    check=False,
                )
                for pattern in [
                    "/root/docker-mi/main.py",
                    "/root/docker-mi/main_nav.py",
                    "robot_navigation.launch.py",
                    "robot_navigation_static.launch.py",
                    "cartographer",
                    "occupancy_grid",
                    "slam_live_map_viewer",
                    "amcl",
                    "map_server",
                    "planner_server",
                    "controller_server",
                    "behavior_server",
                    "bt_navigator",
                    "waypoint_follower",
                    "velocity_smoother",
                    "lifecycle_manager",
                    "dogzilla_cmd_adapter",
                    "dogzilla_state_bridge",
                ]:
                    subprocess.run(["docker", "exec", container, "pkill", "-f", pattern], check=False)
                time.sleep(2)

                if mode == "navigation":
                    map_arg = _build_static_map_arg(
                        data.get("map_arg") or data.get("map_name")
                    )
                    if not map_arg:
                        return _err("navigation mode requires map_arg or map_name", 400)
                        
                    _run_checked(
                        [
                            "docker",
                            "exec",
                            "-d",
                            container,
                            "bash",
                            "-lc",
                            "source /opt/ros/humble/setup.bash && "
                            "source /root/yahboomcar_ws/install/setup.bash && "
                            f"echo 'robot_navigation_static.launch.py{map_arg}' > /tmp/lidar_launch_cmd.log && "
                            f"ros2 launch mi_bringup robot_navigation_static.launch.py{map_arg} "
                            "> /tmp/lidar_ros.log 2>&1",
                        ],
                    )
                else:
                    _run_checked(
                        [
                            "docker",
                            "exec",
                            "-d",
                            container,
                            "bash",
                            "-lc",
                            "source /opt/ros/humble/setup.bash && "
                            "source /root/yahboomcar_ws/install/setup.bash && "
                            "ros2 launch mi_bringup robot_navigation.launch.py "
                            "> /tmp/lidar_ros.log 2>&1",
                        ],
                    )

                time.sleep(8)

                web_main = "/root/docker-mi/main.py" 

                _run_checked(
                    [
                        "docker",
                        "exec",
                        "-d",
                        container,
                        "bash",
                        "-lc",
                        "source /opt/ros/humble/setup.bash && "
                        "source /root/yahboomcar_ws/install/setup.bash && "
                        f"python3 {web_main} "
                        "> /tmp/lidar_map.log 2>&1",
                    ],
                )

            time.sleep(5)

            if mode == "navigation":
                if not _wait_nav2_active(container):
                    ros_log = _tail_in_container(container, "/tmp/lidar_ros.log")
                    map_log = _tail_in_container(container, "/tmp/lidar_map.log")
                    details = []
                    if probe.stdout:
                        details.append(f"map probe: {probe.stdout.strip()}")
                    if probe.stderr:
                        details.append(f"probe stderr: {probe.stderr.strip()}")
                    if ros_log:
                        details.append(f"ros log tail: {ros_log}")
                    if map_log:
                        details.append(f"map log tail: {map_log}")
                    return _err(f"lidar start launched but map service is not ready ({mode}) | " + " | ".join(details), 500)

                return _ok(f"lidar start -> docker ros {mode} + live_map started")

            patterns = [
                "robot_navigation.launch.py",
                "/root/docker-mi/main.py",
                "oradar_scan",
                "cartographer_node",
                "planner_server",
                "controller_server",
                "behavior_server",
                "bt_navigator",
                "waypoint_follower",
                "velocity_smoother",
                "lifecycle_manager",
                "dogzilla_cmd_adapter",
                "dogzilla_state_bridge",
                "cartographer_occupancy_grid_node",
                "dogzilla_state_bridge_2d",
                "obstacle_avoidance_filter",
                "robot_navigation_static.launch.py",
                "/root/docker-mi/main_nav.py",
                "occupancy_grid",
                "slam_live_map_viewer",
                "mi_cartographer","amcl","map_server","static_transform_publisher",
                "cartographer.launch.py",
                
            ]
            for pattern in patterns:
                subprocess.run(["docker", "exec", container, "pkill", "-f", pattern], check=False)
            robot.reconnect_serial()
            return _ok("lidar stop -> docker lidar stack stopped")
        except subprocess.CalledProcessError as e:
            stdout = (e.stdout or "").strip()
            stderr = (e.stderr or "").strip()
            ros_log = _tail_in_container(container, "/tmp/lidar_ros.log")
            map_log = _tail_in_container(container, "/tmp/lidar_map.log")
            details = [f"cmd={e.cmd}"]
            if stdout:
                details.append(f"stdout={stdout}")
            if stderr:
                details.append(f"stderr={stderr}")
            if ros_log:
                details.append(f"ros log tail: {ros_log}")
            if map_log:
                details.append(f"map log tail: {map_log}")
            return _err(f"lidar {action} error | " + " | ".join(details), 500)
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
        lidar_running = _lidar_running()
        return jsonify({
            "server_connected": True,
            "robot_connected": robot.dog is not None or lidar_running,
            "robot_serial_connected": robot.dog is not None,
            "speed_mode": robot.speed_mode(),
            "gait_type": robot.gait_type(),
            "perform_enabled": robot.perform_enabled(),
            "stabilizing_enabled": getattr(robot, "stabilizing_enabled", False),
            "lidar_running": lidar_running,
            "lidar": {
                "running": lidar_running,
            },
            "z_current": robot.z_current(),
            "roll_current": robot.roll_current(),
            "pitch_current": robot.pitch_current(),
            "yaw_current": robot.yaw_current(),
        })

    # ---------- unknown ----------
    return _err(f"unknown command: {cmd}")

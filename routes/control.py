# dogzilla_server/routes/control.py
# -*- coding: utf-8 -*-
from flask import Blueprint, request, jsonify
from ..robot import robot
from .. import config
import os
import signal
import subprocess
bp = Blueprint("control", __name__)


def _ok(result: str = "ok"):
    return jsonify({"ok": True, "result": result}), 200


def _err(msg: str, code: int = 400):
    return jsonify({"ok": False, "error": msg}), code


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


@bp.route("/control", methods=["POST"])
def control():
    data = request.get_json(silent=True) or {}
    cmd = (data.get("command") or "").strip().lower()
    if not cmd:
        return _err("missing 'command' field")

    # ---------- 1) Motion + stop ----------
    if cmd in ("forward", "back", "left", "right", "turnleft", "turnright", "stop"):
        step = data.get("step")
        speed = data.get("speed")
        res = robot.do_motion(cmd, step=step, speed=speed)
        print("[BODY_ADJUST] payload =", res)
        if res.startswith("error"):
            return _err(res, 500)
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

        try:
            if action == "start":
                subprocess.Popen(
                    "bash -lc 'source /opt/ros/humble/setup.bash && ros2 launch mi_bringup robot_navigation.launch.py'",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid,
                )

                time.sleep(2)

                subprocess.Popen(
                    "bash -lc 'python3 /root/mimi_live_map_new/main.py'",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid,
                )

                return _ok("lidar start -> robot_navigation + live_map started")

            else:
                patterns = [
                    "robot_navigation.launch.py",
                    "/root/mimi_live_map_new/main.py",
                ]

                for p in patterns:
                    subprocess.run(
                        f"pkill -f '{p}'",
                        shell=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )

                return _ok("lidar stop -> robot_navigation + live_map stopped")

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

        á» Ä‘Ă¢y ta khĂ´ng map chi tiáº¿t ná»¯a mĂ  giao cho robot.body_adjust()
        trong robot.py xá»­ lĂ½ (clamp + apply xuá»‘ng DOGZILLA náº¿u cĂ³,
        Ä‘á»“ng thá»i lÆ°u state body_offset Ä‘á»ƒ /status dĂ¹ng Ä‘á»“ng bá»™ slider).
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
            "z_current": robot.z_current(),
            "roll_current": robot.roll_current(),
            "pitch_current": robot.pitch_current(),
            "yaw_current": robot.yaw_current(),
        })

    # ---------- unknown ----------
    return _err(f"unknown command: {cmd}")

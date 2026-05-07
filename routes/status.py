# dogzilla_server/routes/status.py
# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify
from ..robot import robot
from .. import config

import os
import subprocess
import time
import re
import socket

bp = Blueprint("status", __name__)
LIDAR_CONTAINER = os.environ.get("DOGZILLA_LIDAR_CONTAINER", "yahboom_humble")
LIDAR_PROCESS_PATTERNS = (
    "/root/docker-mi/main.py",
    "robot_navigation.launch.py",
    "cartographer_node",
    "planner_server",
    "controller_server",
    "behavior_server",
    "bt_navigator",
    "waypoint_follower",
    "velocity_smoother",
    "lifecycle_manager",
    "oradar_scan",
)

def _run_text(command):
    try:
        return subprocess.check_output(
            command,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        ).strip()
    except Exception:
        return ""


def _network_status(signal_percent, connected):
    if not connected:
        return "offline", "Mat ket noi"
    if signal_percent is None:
        return "strong", "Manh"
    if signal_percent >= 75:
        return "strong", "Manh"
    if signal_percent >= 45:
        return "medium", "Trung binh"
    return "weak", "Yeu"


def _get_active_network_info():
    interface = _run_text(["sh", "-lc", "ip route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i==\"dev\") {print $(i+1); exit}}'"])
    ip_addr = _run_text(["sh", "-lc", "ip route get 1.1.1.1 | awk '{for(i=1;i<=NF;i++) if($i==\"src\") {print $(i+1); exit}}'"])
    gateway = _run_text(["sh", "-lc", "ip route | awk '/default/ {print $3; exit}'"])

    if not interface:
        interface = _run_text(["sh", "-lc", "ip -o -4 addr show scope global | awk '{print $2; exit}'"])
    if not ip_addr:
        ip_addr = _get_local_ip()

    network_type = "wifi" if interface.startswith(("wl", "wlan")) else "ethernet" if interface.startswith(("eth", "en")) else "unknown"
    ssid = ""
    signal_percent = None
    signal_dbm = None

    if network_type == "wifi":
        ssid = _run_text(["iwgetid", interface, "-r"])
        if not ssid:
            ssid = _run_text(["sh", "-lc", "nmcli -t -f active,ssid dev wifi | awk -F: '$1==\"yes\" {print $2; exit}'"])

        raw_signal = _run_text(["sh", "-lc", "nmcli -t -f in-use,signal dev wifi | awk -F: '$1==\"*\" {print $2; exit}'"])
        if raw_signal:
            try:
                signal_percent = max(0, min(100, int(float(raw_signal))))
            except Exception:
                signal_percent = None

        if signal_percent is None:
            wireless_line = _run_text(["sh", "-lc", f"awk '$1 ~ /{interface}:/ {{print $3, $4; exit}}' /proc/net/wireless"])
            parts = wireless_line.split()
            if parts:
                try:
                    quality = float(parts[0].strip("."))
                    signal_percent = max(0, min(100, round((quality / 70.0) * 100)))
                except Exception:
                    signal_percent = None
            if len(parts) > 1:
                try:
                    signal_dbm = float(parts[1].strip("."))
                except Exception:
                    signal_dbm = None

    connected = bool(ip_addr and ip_addr != "x.x.x.x")
    status_value, status_label = _network_status(signal_percent, connected)
    name = ssid or interface or "Unknown network"

    return {
        "connected": connected,
        "name": name,
        "ssid": ssid or None,
        "interface": interface or None,
        "type": network_type,
        "ip": ip_addr if ip_addr != "x.x.x.x" else None,
        "gateway": gateway or None,
        "signal_percent": signal_percent,
        "signal_dbm": signal_dbm,
        "status": status_value,
        "status_label": status_label,
        "summary": f"{name} - {status_label}" if connected else status_label,
        "timestamp": int(time.time()),
    }


# ===== Helpers: đọc system info từ Pi =====

def _get_cpu_usage_percent():
    try:
        def read_cpu_line():
            with open("/proc/stat", "r") as f:
                line = f.readline()
            parts = [int(p) for p in line.split()[1:11]]
            total = sum(parts)
            idle = parts[3]
            return total, idle

        total1, idle1 = read_cpu_line()
        time.sleep(0.1)
        total2, idle2 = read_cpu_line()

        total = total2 - total1
        idle = idle2 - idle1
        if total <= 0:
            return 0
        return int((total - idle) * 100 / total)
    except Exception as e:
        print("[Status] _get_cpu_usage_percent error:", e)
        return None


def _get_ram_usage_string():
    try:
        cmd = "free | awk 'NR==2{printf \"RAM:%2d%% -> %.1fGB\", 100*($2-$7)/$2, ($2/1048576.0)}'"
        out = subprocess.check_output(cmd, shell=True)
        return out.decode("utf-8")
    except Exception as e:
        print("[Status] _get_ram_usage_string error:", e)
        return None


def _get_disk_usage_string():
    try:
        cmd = "df -h | awk '$NF==\"/\"{printf \"SDC:%s : %.1fGB\", $5, $2}'"
        out = subprocess.check_output(cmd, shell=True)
        return out.decode("utf-8")
    except Exception as e:
        print("[Status] _get_disk_usage_string error:", e)
        return None


def _get_local_ip():
    """
    Tr? v? IP n?i b? c?a Pi.
    �u ti�n:
      1) config.HOST_IP (n?u b?n c� set trong config.py)
      2) `hostname -I` (l?y IPv4 �?u ti�n)
      3) eth0 / wlan0
      4) fallback 'x.x.x.x'
    """
    # 1) N?u b?n mu?n fix c?ng IP trong config
    host_ip = getattr(config, "HOST_IP", None)
    if host_ip:
        return str(host_ip)

    # 2) Th? hostname -I (tr? list IP tr�n 1 d?ng)
    try:
        out = subprocess.check_output("hostname -I", shell=True).decode("utf-8").strip()
        # l?y IPv4 �?u ti�n
        for token in out.split():
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", token):
                return token
    except Exception as e:
        print("[Status] hostname -I error:", e)

    # 3) Th? eth0 / wlan0 v?i ip/ifconfig
    for iface in ("eth0", "wlan0"):
        try:
            cmd = f"ip addr show {iface} | grep 'inet ' | awk '{{print $2}}' | cut -d'/' -f1"
            ip = os.popen(cmd).read().strip()
            if ip and re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
                return ip
        except Exception as e:
            print(f"[Status] get ip for {iface} error:", e)

    # 4) Fallback
    return "x.x.x.x"
def _get_system_time():
    try:
        cmd = "date +%H:%M:%S"
        out = subprocess.check_output(cmd, shell=True)
        return out.decode("utf-8").strip()
    except Exception as e:
        print("[Status] _get_system_time error:", e)
        return None


def _lidar_process_running():
    try:
        pattern_expr = " | ".join(LIDAR_PROCESS_PATTERNS)
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


def _lidar_running():
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                LIDAR_CONTAINER,
                "bash",
                "-lc",
                "python3 - <<'PY'\n"
                "import sys, urllib.request\n"
                "try:\n"
                "    with urllib.request.urlopen('http://127.0.0.1:8080/state', timeout=1.5) as r:\n"
                "        sys.exit(0 if 200 <= int(getattr(r, 'status', 0)) < 300 else 1)\n"
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
            return True
    except Exception:
        pass
    return False


@bp.route("/network", methods=["GET"])
def network():
    try:
        return jsonify({"ok": True, **_get_active_network_info()})
    except Exception as e:
        return jsonify({
            "ok": False,
            "connected": False,
            "name": "Unknown network",
            "status": "offline",
            "status_label": "Mat ket noi",
            "summary": "Mat ket noi",
            "error": str(e),
        }), 500


@bp.route("/status", methods=["GET", "POST"])
def status():
    """
    Trả JSON cho Django ROSClient.get_status().
    Vẫn giữ các field cũ, nhưng thêm block "system" cho frontend.
    """

    battery = None
    voltage = 11.4
    fw      = None

    lidar_running = _lidar_running()

    if robot.dog is not None and not lidar_running:
        try:
            if hasattr(robot.dog, "read_battery"):
                battery = robot.dog.read_battery()
        except Exception as e:
            print("[Status] read_battery error:", e)
            battery = None
        try:
            if battery is not None:
                voltage = round(9.0 + (battery / 100.0) * 3.6, 2)
        except Exception as e:
            print("[Status] voltage compute error:", e)
            voltage = 11.4
        try:
            if hasattr(robot.dog, "read_version"):
                fw = robot.dog.read_version()
        except Exception as e:
            print("[Status] read_version error:", e)

    cpu_percent = _get_cpu_usage_percent()
    ram_str     = _get_ram_usage_string()
    disk_str    = _get_disk_usage_string()
    ip_addr     = _get_local_ip()
    t_now       = _get_system_time()

    try:
        data = {
            "robot_connected": robot.dog is not None,
            "speed_mode": robot.speed_mode(),
            "gait_type": robot.gait_type(),
            "perform_enabled": robot.perform_enabled(),
            "stabilizing_enabled": getattr(robot, "stabilizing_enabled", False),
            "lidar_running": lidar_running,
            "turn_speed_range": [
                getattr(config, "TURN_MIN", -70),
                getattr(config, "TURN_MAX",  70),
            ],
            "step_default": getattr(config, "STEP_DEFAULT", 10),
            "z_range": [
                getattr(config, "Z_MIN", 75),
                getattr(config, "Z_MAX", 115),
            ],
            "z_current": robot.z_current(),
            "roll_current": robot.roll_current(),
            "pitch_range": [
                getattr(config, "PITCH_MIN", -30.0),
                getattr(config, "PITCH_MAX",  30.0),
            ],
            "pitch_current": robot.pitch_current(),
            "yaw_current": robot.yaw_current(),
            "battery": battery,
            "voltage": voltage,
            "fw": fw,
            "fps": getattr(config, "FRAME_FPS", 30),
            "system": {
                "cpu_percent": cpu_percent,
                "ram":  ram_str,
                "disk": disk_str,
                "ip":   ip_addr,
                "time": t_now,
            },
        }
        return jsonify(data)
    except Exception as e:
        print("[Status] route build error:", e)
        return jsonify({
            "robot_connected": robot.dog is not None,
            "speed_mode": "unknown",
            "gait_type": "unknown",
            "perform_enabled": False,
            "stabilizing_enabled": getattr(robot, "stabilizing_enabled", False),
            "lidar_running": lidar_running,
            "battery": battery,
            "voltage": voltage,
            "fw": fw,
            "fps": getattr(config, "FRAME_FPS", 30),
            "system": {
                "cpu_percent": cpu_percent,
                "ram": ram_str,
                "disk": disk_str,
                "ip": ip_addr,
                "time": t_now,
            },
            "status_error": str(e),
        })

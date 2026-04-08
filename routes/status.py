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
    Return local IP address of the Pi.
    Priority:
      1) config.HOST_IP (if configured in config.py)
      2) `hostname -I` (first IPv4 token)
      3) eth0 / wlan0
      4) fallback 'x.x.x.x'
    """
    # 1) Use fixed IP from config if provided.
    host_ip = getattr(config, "HOST_IP", None)
    if host_ip:
        return str(host_ip)

    # 2) Try `hostname -I` (returns a list of IPs on one line)
    try:
        out = subprocess.check_output("hostname -I", shell=True).decode("utf-8").strip()
        # take the first IPv4 token
        for token in out.split():
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", token):
                return token
    except Exception as e:
        print("[Status] hostname -I error:", e)

    # 3) Try eth0/wlan0 via ip/ifconfig.
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


@bp.route("/status", methods=["GET", "POST"])
def status():
    """
    Trả JSON cho Django ROSClient.get_status().
    Vẫn giữ các field cũ, nhưng thêm block "system" cho frontend.
    """

    battery = None
    fw      = None

    if robot.dog is not None:
        try:
            if hasattr(robot.dog, "read_battery"):
                battery = robot.dog.read_battery()
        except Exception as e:
            # print("[Status] read_battery error:", e)
            battery = robot.dog.read_battery()
        # try:
        #     if hasattr(robot.dog, "read_version"):
        #         fw = robot.dog.read_version()
        #except Exception as e:
            # print("[Status] read_version error:", e)

    cpu_percent = _get_cpu_usage_percent()
    ram_str     = _get_ram_usage_string()
    disk_str    = _get_disk_usage_string()
    ip_addr     = _get_local_ip()
    t_now       = _get_system_time()

    data = {
        "robot_connected": robot.dog is not None,
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
        "pitch_range": [
            getattr(config, "PITCH_MIN", -30.0),
            getattr(config, "PITCH_MAX",  30.0),
        ],
        "pitch_current": robot.pitch_current(),
        "battery": battery,
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

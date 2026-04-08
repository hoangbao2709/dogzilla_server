# dogzilla_server/system_info.py
import os
import subprocess
import time

from DOGZILLALib import DOGZILLA

# Shared DOGZILLA instance
g_dog = DOGZILLA()

# ===== CPU =====
def get_cpu_usage_percent():
    """Read near-real-time CPU percent using two /proc/stat samples."""
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
    usage = int((total - idle) * 100 / total)
    return usage

# ===== RAM =====
def get_ram_usage_string():
    """
    Example format: 'RAM:23% -> 3.9GB'
    Similar to getUsagedRAM() on OLED.
    """
    cmd = "free | awk 'NR==2{printf \"RAM:%2d%% -> %.1fGB\", 100*($2-$7)/$2, ($2/1048576.0)}'"
    out = subprocess.check_output(cmd, shell=True)
    s = out.decode("utf-8")
    return s

# ===== Disk =====
def get_disk_usage_string():
    """
    Example format: 'SDC:23% -> 28.8GB'
    Similar to getUsagedDisk() on OLED.
    """
    cmd = "df -h | awk '$NF==\"/\"{printf \"SDC:%s -> %.1fGB\", $5, $2}'"
    out = subprocess.check_output(cmd, shell=True)
    s = out.decode("utf-8")
    return s

# ===== IP =====
def get_local_ip():
    ip = os.popen("/sbin/ifconfig eth0 | grep 'inet' | awk '{print $2}'").read().strip()
    if not ip or len(ip) > 15:
        ip = os.popen("/sbin/ifconfig wlan0 | grep 'inet' | awk '{print $2}'").read().strip()
        if not ip:
            ip = "x.x.x.x"
    if len(ip) > 15:
        ip = "x.x.x.x"
    return ip

# ===== Time =====
def get_system_time():
    cmd = "date +%H:%M:%S"
    out = subprocess.check_output(cmd, shell=True)
    return out.decode("utf-8").strip()

# ===== Battery =====
def get_battery_percent():
    """Read DOGZILLA battery percentage, return int or None on error."""
    try:
        val = g_dog.read_battery()
        # If read fails or returns 0, caller can apply additional handling.
        return int(val)
    except Exception as e:
        # print("[system_info] read_battery error:", e)
        return None


def get_all_status():
    """Collect all status values into one dict for JSON response."""
    cpu = get_cpu_usage_percent()
    ram_str = get_ram_usage_string()
    disk_str = get_disk_usage_string()
    ip = get_local_ip()
    t = get_system_time()
    bat = get_battery_percent()

    return {
        "cpu_percent": cpu,
        "ram": ram_str,
        "disk": disk_str,
        "ip": ip,
        "time": t,
        "battery_percent": bat,
    }

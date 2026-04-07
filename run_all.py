#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import time
import sys

DOCKER = "yahboom_humble"

def check_or_start_container():
    """Ki?m tra container c� t?n t?i & �ang ch?y ch�a, n?u ch�a th? docker start."""
    print("=== CHECK / START CONTAINER ===")
    inspect = subprocess.run(
        f"docker inspect -f '{{{{.State.Running}}}}' {DOCKER}",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if inspect.returncode != 0:
        print(f"? Kh�ng t?m th?y container t�n '{DOCKER}'.")
        print("   ? Ch?y th?: docker ps -a �? ki?m tra.")
        sys.exit(1)

    running = inspect.stdout.strip()
    if running == "true":
        print(f"? Container '{DOCKER}' �ang ch?y.")
        return

    print(f"? Container '{DOCKER}' ch�a ch?y ? docker start {DOCKER}")
    start = subprocess.run(f"docker start {DOCKER}", shell=True)
    if start.returncode != 0:
        print("? docker start b? l?i, ki?m tra l?i container.")
        sys.exit(start.returncode)

    print("? �? start container xong.")


def exec_in_container(cmd: str):
    """
    Ch?y l?nh trong container, log in tr?c ti?p ra m�n h?nh.
    D�ng bash -lc �? source + cd ho?t �?ng b?nh th�?ng.
    """
    full_cmd = f"docker exec -i {DOCKER} bash -lc \"{cmd}\""

    print("\n>>> RUN:", full_cmd)
    return subprocess.Popen(full_cmd, shell=True)


def main():
    check_or_start_container()

    print("\n=== STARTING ALL SERVICES ===")

    # Chu?i common: source ROS + workspace
    env_source = (
        "source /opt/ros/humble/setup.bash && "
        "source /root/yahboomcar_ws/install/setup.bash && "
    )

    # 1?? Cartographer + MS200
    p1 = exec_in_container(
        env_source +
        "ros2 launch /root/yahboomcar_ws/src/yahboom_bringup/launch/ms200_with_cartographer_norviz.launch.py "
        "cartographer_config_dir:=/root/yahboomcar_ws/src/yahboom_bringup/config "
        "configuration_basename:=xgo_2d.lua "
        "launch_rviz:=false"
    )
    print("[OK] �? g?i l?nh Cartographer")
    time.sleep(3)

    # 2?? Web SLAM + A*
    p2 = exec_in_container(
        env_source +
        "cd /root/my_lidar_tools && "
        "python3 slam_live_map.py"
    )
    print("[OK] �? g?i l?nh SLAM web server")
    time.sleep(1)

    # 3?? Path follower
    p3 = exec_in_container(
        env_source +
        "cd /root/my_lidar_tools && "
        "python3 dogzilla_path_follower.py"
    )
    print("[OK] �? g?i l?nh Dogzilla follower")

    print("\n=== ALL SERVICES STARTED (theo d?i log ngay b�n d�?i) ===")
    print("Nh?n Ctrl + C �? d?ng script n�y (c�c process trong container c� th? v?n ch?y n?u b?n kh�ng kill).")
    print("N?u c?n t?t h?n, c� th? v�o container r?i d�ng `ps aux | grep python` v� `kill`.\n")

    try:
        p1.wait()
        p2.wait()
        p3.wait()
    except KeyboardInterrupt:
        print("\n? B?n v?a nh?n Ctrl + C � script d?ng, container v?n ch?y.")
        print("N?u mu?n d?ng ROS/SLAM/follower th? v�o container v� kill PID t��ng ?ng.\n")


if __name__ == "__main__":
    main()

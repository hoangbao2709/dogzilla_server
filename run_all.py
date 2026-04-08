#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import time
import sys

DOCKER = "yahboom_humble"

def check_or_start_container():
    """Check if container exists/running; start it when needed."""
    print("=== CHECK / START CONTAINER ===")
    inspect = subprocess.run(
        f"docker inspect -f '{{{{.State.Running}}}}' {DOCKER}",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if inspect.returncode != 0:
        print(f"[ERROR] Container '{DOCKER}' was not found.")
        print("        Run: docker ps -a")
        sys.exit(1)

    running = inspect.stdout.strip()
    if running == "true":
        print(f"[OK] Container '{DOCKER}' is already running.")
        return

    print(f"[INFO] Container '{DOCKER}' is stopped -> docker start {DOCKER}")
    start = subprocess.run(f"docker start {DOCKER}", shell=True)
    if start.returncode != 0:
        print("[ERROR] docker start failed. Please check container status.")
        sys.exit(start.returncode)

    print("[OK] Container started.")


def exec_in_container(cmd: str):
    """
    Run command inside container and stream logs to console.
    Use bash -lc so source/cd work as expected.
    """
    full_cmd = f"docker exec -i {DOCKER} bash -lc \"{cmd}\""

    print("\n>>> RUN:", full_cmd)
    return subprocess.Popen(full_cmd, shell=True)


def main():
    check_or_start_container()

    print("\n=== STARTING ALL SERVICES ===")

    # Shared command prefix: source ROS + workspace.
    env_source = (
        "source /opt/ros/humble/setup.bash && "
        "source /root/yahboomcar_ws/install/setup.bash && "
    )

    # 1) Cartographer + MS200.
    p1 = exec_in_container(
        env_source +
        "ros2 launch /root/yahboomcar_ws/src/yahboom_bringup/launch/ms200_with_cartographer_norviz.launch.py "
        "cartographer_config_dir:=/root/yahboomcar_ws/src/yahboom_bringup/config "
        "configuration_basename:=xgo_2d.lua "
        "launch_rviz:=false"
    )
    print("[OK] Cartographer launch command sent.")
    time.sleep(3)

    # 2) Web SLAM + A*.
    p2 = exec_in_container(
        env_source +
        "cd /root/my_lidar_tools && "
        "python3 slam_live_map.py"
    )
    print("[OK] SLAM web server command sent.")
    time.sleep(1)

    # 3) Path follower.
    p3 = exec_in_container(
        env_source +
        "cd /root/my_lidar_tools && "
        "python3 dogzilla_path_follower.py"
    )
    print("[OK] Dogzilla follower command sent.")

    print("\n=== ALL SERVICES STARTED (logs continue below) ===")
    print("Press Ctrl+C to stop this script (processes in container may keep running).")
    print("For cleanup, enter container and use `ps aux | grep python` then `kill`.\n")

    try:
        p1.wait()
        p2.wait()
        p3.wait()
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C received. Script stops, container may still run.")
        print("To stop ROS/SLAM/follower, enter container and kill related PIDs.\n")


if __name__ == "__main__":
    main()

from __future__ import annotations

import logging
import os
import sys
from typing import Literal

import requests
from fastmcp import FastMCP

logger = logging.getLogger("RobotController")

if sys.platform == "win32":
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

mcp = FastMCP("RobotController")

ROBOT_IP = os.getenv("ROBOT_IP", "127.0.0.1")
ROBOT_PORT = os.getenv("ROBOT_PORT", "9000")
REQUEST_TIMEOUT = float(os.getenv("ROBOT_TIMEOUT", "5"))
CONTROL_URL = f"http://{ROBOT_IP}:{ROBOT_PORT}/control"

POSTURES = {
    "Lie_Down",
    "Stand_Up",
    "Crawl",
    "Squat",
    "Sit_Down",
}

BEHAVIORS = {
    "Turn_Around",
    "Mark_Time",
    "Turn_Roll",
    "Turn_Pitch",
    "Turn_Yaw",
    "3_Axis",
    "Pee",
    "Wave_Hand",
    "Stretch",
    "Wave_Body",
    "Swing",
    "Pray",
    "Seek",
    "Handshake",
    "Play_Ball",
}


def send_control(payload: dict) -> dict:
    try:
        response = requests.post(CONTROL_URL, json=payload, timeout=REQUEST_TIMEOUT)
        response_text = response.text
        try:
            response_body = response.json()
        except ValueError:
            response_body = {"raw": response_text}

        result = {
            "success": response.ok,
            "url": CONTROL_URL,
            "status_code": response.status_code,
            "payload": payload,
            "response": response_body,
        }
        logger.info("Sent payload=%s status=%s", payload, response.status_code)
        return result
    except requests.RequestException as exc:
        logger.error("Failed to send payload=%s error=%s", payload, exc)
        return {
            "success": False,
            "url": CONTROL_URL,
            "payload": payload,
            "error": str(exc),
        }


@mcp.tool()
def reset_robot() -> dict:
    """Reset the robot to its default state."""
    return send_control({"command": "reset"})


@mcp.tool()
def rotation() -> dict:
    """Trigger the robot rotation command."""
    return send_control({"command": "rotation"})


@mcp.tool()
def set_posture(
    name: Literal["Lie_Down", "Stand_Up", "Crawl", "Squat", "Sit_Down"]
) -> dict:
    """Set the robot posture using one of the supported posture names."""
    if name not in POSTURES:
        return {"success": False, "error": f"Invalid posture: {name}"}
    return send_control({"command": "posture", "name": name})


@mcp.tool()
def play_behavior(
    name: Literal[
        "Turn_Around",
        "Mark_Time",
        "Turn_Roll",
        "Turn_Pitch",
        "Turn_Yaw",
        "3_Axis",
        "Pee",
        "Wave_Hand",
        "Stretch",
        "Wave_Body",
        "Swing",
        "Pray",
        "Seek",
        "Handshake",
        "Play_Ball",
    ]
) -> dict:
    """Play a predefined robot behavior such as Handshake, Wave_Hand, or Play_Ball."""
    if name not in BEHAVIORS:
        return {"success": False, "error": f"Invalid behavior: {name}"}
    return send_control({"command": "behavior", "name": name})


if __name__ == "__main__":
    mcp.run(transport="stdio")

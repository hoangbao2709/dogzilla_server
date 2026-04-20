from __future__ import annotations

import asyncio
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("LaptopVoiceBridge")

app = Flask(__name__, static_folder="static", static_url_path="/static")

SERVER_SCRIPT = str(BASE_DIR / "robot_mcp_server.py")
CHILD_ENV = {
    "ROBOT_IP": os.getenv("ROBOT_IP", "127.0.0.1"),
    "ROBOT_PORT": os.getenv("ROBOT_PORT", "9000"),
    "ROBOT_TIMEOUT": os.getenv("ROBOT_TIMEOUT", "5"),
    "LOG_LEVEL": os.getenv("LOG_LEVEL", "INFO"),
}

POSTURE_KEYWORDS = {
    "Lie_Down": ["nam xuong", "nằm xuống", "lie down"],
    "Stand_Up": ["dung len", "đứng lên", "stand up"],
    "Crawl": ["bo", "bò", "crawl"],
    "Squat": ["ngoi xuong", "ngồi xuống", "squat"],
    "Sit_Down": ["ngoi", "ngồi", "sit down"],
}

BEHAVIOR_KEYWORDS = {
    "Turn_Around": ["xoay vong", "quay vong", "turn around"],
    "Mark_Time": ["di bo tai cho", "giậm chân tại chỗ", "mark time"],
    "Turn_Roll": ["roll", "lăn"],
    "Turn_Pitch": ["pitch", "gật"],
    "Turn_Yaw": ["yaw", "xoay dau"],
    "3_Axis": ["3 truc", "ba trục", "3 axis"],
    "Pee": ["pee", "đi vệ sinh giả"],
    "Wave_Hand": ["bat tay chao", "vẫy tay", "wave hand"],
    "Stretch": ["vuon minh", "stretch"],
    "Wave_Body": ["lac nguoi", "lắc người", "wave body"],
    "Swing": ["du dua", "đung đưa", "swing"],
    "Pray": ["cau nguyen", "cầu nguyện", "pray"],
    "Seek": ["tim kiem", "tìm kiếm", "seek"],
    "Handshake": ["bat tay", "bắt tay", "handshake"],
    "Play_Ball": ["choi bong", "chơi bóng", "play ball"],
}

DIRECT_COMMANDS = {
    "reset": ["reset", "dat lai", "đặt lại", "ve mac dinh", "về mặc định"],
    "rotation": ["rotation", "xoay", "quay tron", "quay tròn"],
}


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")



def normalize_text(text: str) -> str:
    text = strip_accents(text.lower()).replace("_", " ")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text



def find_first_match(normalized: str, mapping: dict[str, list[str]]) -> str | None:
    for target, keywords in mapping.items():
        for keyword in keywords:
            if normalize_text(keyword) in normalized:
                return target
    return None

def parse_navigation_command(text: str) -> dict[str, Any] | None:
    normalized = normalize_text(text)

    # đi tới điểm A
    m = re.search(r"\b(di toi|di den)\s+(diem\s+)?([a-z])\b", normalized)
    if m:
        point = m.group(3).upper()
        return {
            "tool": "goto_point",
            "arguments": {"name": point},
            "matched": f"point_{point}",
            "normalized_text": normalized,
            "intent": "navigation",
        }

    # đi qua A B C
    m = re.search(r"\b(di qua|toi qua)\s+((?:[a-z]\s*)+)$", normalized)
    if m:
        points = re.findall(r"[a-z]", m.group(2))
        points = [p.upper() for p in points]
        if points:
            return {
                "tool": "goto_waypoints",
                "arguments": {"points": points},
                "matched": points,
                "normalized_text": normalized,
                "intent": "navigation",
            }

    # dừng di chuyển
    if "dung di chuyen" in normalized or "dung lai" in normalized:
        return {
            "tool": "stop_navigation",
            "arguments": {},
            "matched": "stop_navigation",
            "normalized_text": normalized,
            "intent": "navigation",
        }

    return None

def map_text_to_mcp(text: str) -> dict[str, Any]:
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("Không nhận được nội dung giọng nói.")

    # Ưu tiên lệnh điều hướng trước
    nav = parse_navigation_command(text)
    if nav:
        return nav

    direct = find_first_match(normalized, DIRECT_COMMANDS)
    if direct == "reset":
        return {
            "tool": "reset_robot",
            "arguments": {},
            "matched": "reset",
            "normalized_text": normalized,
        }
    if direct == "rotation":
        return {
            "tool": "rotation",
            "arguments": {},
            "matched": "rotation",
            "normalized_text": normalized,
        }

    posture = find_first_match(normalized, POSTURE_KEYWORDS)
    if posture:
        return {
            "tool": "set_posture",
            "arguments": {"name": posture},
            "matched": posture,
            "normalized_text": normalized,
        }

    behavior = find_first_match(normalized, BEHAVIOR_KEYWORDS)
    if behavior:
        return {
            "tool": "play_behavior",
            "arguments": {"name": behavior},
            "matched": behavior,
            "normalized_text": normalized,
        }

    raise ValueError(f"Chưa map được câu lệnh: '{text}'")


async def call_mcp_tool(tool_name: str, arguments: dict[str, Any]) -> Any:
    transport = StdioTransport(
        command="python",
        args=[SERVER_SCRIPT],
        env=CHILD_ENV,
        cwd=str(BASE_DIR),
        keep_alive=False,
    )
    client = Client(transport)
    async with client:
        result = await client.call_tool(tool_name, arguments)
        if hasattr(result, "data"):
            return result.data
        if hasattr(result, "structured_content"):
            return result.structured_content
        return str(result)


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "voice_control.html")


@app.get("/api/health")
def health():
    return jsonify({
        "ok": True,
        "robot_server": SERVER_SCRIPT,
        "robot_ip": CHILD_ENV["ROBOT_IP"],
        "robot_port": CHILD_ENV["ROBOT_PORT"],
    })


@app.post("/api/text-command")
def text_command():
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()

    if not text:
        return jsonify({"success": False, "error": "Thiếu trường 'text'."}), 400

    try:
        mapped = map_text_to_mcp(text)
        result = asyncio.run(call_mcp_tool(mapped["tool"], mapped["arguments"]))
        return jsonify(
            {
                "success": True,
                "input_text": text,
                "mapped": mapped,
                "mcp_result": result,
            }
        )
    except ValueError as exc:
        return jsonify({"success": False, "input_text": text, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("Failed to execute command")
        return jsonify({"success": False, "input_text": text, "error": str(exc)}), 500


if __name__ == "__main__":
    host = os.getenv("VOICE_BRIDGE_HOST", "0.0.0.0")
    port = int(os.getenv("VOICE_BRIDGE_PORT", "8765"))
    app.run(host=host, port=port, debug=False)

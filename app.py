# -*- coding: utf-8 -*-
from flask import Flask, jsonify, request
import atexit
from pathlib import Path
from . import config, create_app
from .camera import init_camera, cleanup_camera
from .routes.control import bp as control_bp
from .routes.status import bp as status_bp
from .routes.camera import bp as camera_bp
from flask_cors import CORS
import json


from .robot import robot   # d�ng singleton Robot d� t?o + joystick
LINK_FILE = Path.home() / ".robot_link.json"  # /home/pi/.robot_link.json

app = Flask(__name__)

import logging
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

srv_log = logging.getLogger("robot_server")
srv_log.setLevel(logging.INFO)
if not srv_log.handlers:
    h = logging.StreamHandler()
    fmt = logging.Formatter("[RobotServer] %(message)s")
    h.setFormatter(fmt)
    srv_log.addHandler(h)

app.register_blueprint(control_bp)
app.register_blueprint(status_bp)
app.register_blueprint(camera_bp)
CORS(app, resources={r"/*": {"origins": "*"}})
@app.route("/")
def root():
    return jsonify({
        "status": "ok",
        "endpoints": {
            "control": "POST /control",
            "status": "GET /status",
            "camera": "GET /camera (MJPEG)",
            "frame": "GET /frame (single JPEG)",
            "speed_mode": "POST /control {command: speed_mode|pace, mode: slow|normal|high}",
            "attitude": "POST /control {command: setroll|setpitch|setyaw|adjustroll|adjustpitch|adjustyaw, value?|delta?}",
            "z_control": "POST /control {command: setz|adjustz, value?|delta?}",
            "gait_type": "POST /control {command: gait_type, mode: trot|walk|high_walk}",
            "perform": "POST /control {command: perform, action: on|off}",
            "mark_time": "POST /control {command: mark_time, value: 0..35}",
            "reset": "POST /control {command: reset}"
        }
    })

@app.route("/test")
def test_page():
    return """
<!doctype html>
<html>
  <body>
    <h3>/frame (single JPEG)</h3>
    <img src="/frame" width="640" height="480"/>
    <h3>/camera (MJPEG)</h3>
    <img src="/camera" width="640" height="480"/>
  </body>
</html>
"""

@app.route("/health")
def health():
    return jsonify({"ok": True})

# --- Camera init ---
init_camera()
atexit.register(cleanup_camera)

# --- START JOYSTICK TAY C?M ---
# (ch?y 1 l?n khi process Flask du?c import)
robot.start_joystick(
    debug=getattr(config, "JOYSTICK_DEBUG", False),
    js_id=getattr(config, "JOYSTICK_ID", 0),
)
@app.route("/link-account", methods=["POST"])
def link_account():
    try:
        data = request.get_json(force=True)
    except:
        return jsonify({"ok": False, "error": "Invalid JSON"}), 400

    email = data.get("email")
    device_id = data.get("device_id")

    if not email or not device_id:
        return jsonify({"ok": False, "error": "email and device_id required"}), 400

    # L�u v�o file
    with open(LINK_FILE, "w") as f:
        json.dump({"email": email, "device_id": device_id}, f)

    return jsonify({"ok": True})

if __name__ == "__main__":
    print(f"[Server] HTTP_PORT={config.HTTP_PORT}  CAMERA_INDEX={config.CAMERA_INDEX}  "
         f"DOG={config.DOG_PORT}@{config.DOG_BAUD}")
    app.run(host="0.0.0.0", port=config.HTTP_PORT, threaded=True)

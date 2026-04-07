from flask import Flask, jsonify
from . import config
from .camera import init_camera, cleanup_camera
from .routes.control import bp as control_bp
from .routes.camera import bp as camera_bp
from .routes.status import bp as status_bp


def create_app() -> Flask:
    app = Flask(__name__)

    # init camera
    init_camera()

    # register routes
    app.register_blueprint(control_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(status_bp)

    @app.route("/")
    def root():
        return jsonify({
            "status": "ok",
            "endpoints": {
                "control": "POST /control  {command: forward|back|left|right|turnleft|turnright|stop|setz|adjustz|status, step?: int, speed?: int, value?: int, delta?: int}",
                "camera": "GET /camera (MJPEG)",
                "status": "GET/POST /status"
            }
        })

    # cleanup on teardown
    @app.teardown_appcontext
    def _cleanup(_exc):
        cleanup_camera()

    return app
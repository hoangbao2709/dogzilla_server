# -*- coding: utf-8 -*-
from flask import Blueprint
from ..camera import camera_response, single_frame_response

bp = Blueprint("camera", __name__)

@bp.route("/camera")
def camera_feed():
    return camera_response()

# Fallback: single JPEG frame for test/poll
@bp.route("/frame")
def camera_frame():
    return single_frame_response()

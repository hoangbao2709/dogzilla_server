# -*- coding: utf-8 -*-
import time
import threading
import numpy as np
from flask import Response, stream_with_context
from . import config

cv2 = None
_cap = None

_frame_lock = threading.Lock()
_latest_jpeg = None
_reader_thread = None
_running = False


def _open_camera():
    global cv2, _cap
    try:
        import cv2 as _cv2
        cv2 = _cv2

        cam = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_V4L2)
        if not cam.isOpened():
            cam = cv2.VideoCapture(config.CAMERA_INDEX)

        if not cam.isOpened():
            print(f"[Camera] Cannot open index {config.CAMERA_INDEX}")
            _cap = None
            return

        cam.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_W)
        cam.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_H)
        cam.set(cv2.CAP_PROP_FPS, config.FRAME_FPS)

        # Giảm buffer để lấy frame mới nhất
        try:
            cam.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Thử MJPG để camera encode sẵn nếu thiết bị hỗ trợ
        try:
            cam.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        except Exception:
            pass

        _cap = cam
        print(
            f"[Camera] Opened index {config.CAMERA_INDEX} "
            f"({config.FRAME_W}x{config.FRAME_H} @ {config.FRAME_FPS}fps)"
        )
    except Exception as e:
        print("[Camera] Init error:", e)
        _cap = None


def _blank_jpeg():
    if cv2 is None:
        return b""
    img = np.zeros((config.FRAME_H, config.FRAME_W, 3), dtype=np.uint8)
    ok, buf = cv2.imencode(
        ".jpg",
        img,
        [int(cv2.IMWRITE_JPEG_QUALITY), getattr(config, "JPEG_QUALITY", 60)],
    )
    return buf.tobytes() if ok else b""


def _camera_reader_loop():
    global _latest_jpeg, _running

    target_fps = max(1, int(getattr(config, "STREAM_FPS", config.FRAME_FPS)))
    frame_period = 1.0 / float(target_fps)

    while _running:
        t0 = time.time()

        if _cap is None or cv2 is None:
            jpg = _blank_jpeg()
            with _frame_lock:
                _latest_jpeg = jpg
            time.sleep(0.2)
            continue

        ok, frame = _cap.read()
        if not ok or frame is None:
            time.sleep(0.01)
            continue

        # Encode ngay tại thread đọc camera
        ok, buf = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), getattr(config, "JPEG_QUALITY", 70)],
        )
        if not ok:
            continue

        jpg = buf.tobytes()

        with _frame_lock:
            _latest_jpeg = jpg

        dt = time.time() - t0
        sleep_left = frame_period - dt
        if sleep_left > 0:
            time.sleep(sleep_left)


def init_camera():
    global _reader_thread, _running, _latest_jpeg

    if _cap is None:
        _open_camera()

    if _latest_jpeg is None:
        _latest_jpeg = _blank_jpeg()

    if _reader_thread is None:
        _running = True
        _reader_thread = threading.Thread(target=_camera_reader_loop, daemon=True)
        _reader_thread.start()
        print("[Camera] Reader thread started")


def _get_latest_jpeg():
    with _frame_lock:
        return _latest_jpeg if _latest_jpeg is not None else _blank_jpeg()


def mjpeg_generator():
    boundary = b"--frame"
    last_sent = None

    # Chỉ gửi frame mới nhất, không tự đọc camera ở đây nữa
    while True:
        jpg = _get_latest_jpeg()

        # Nếu muốn giảm spam network, chỉ gửi khi frame đổi
        if jpg != last_sent and jpg:
            header = (
                boundary
                + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                + str(len(jpg)).encode()
                + b"\r\n\r\n"
            )
            yield header + jpg + b"\r\n"
            last_sent = jpg
        else:
            # nghỉ rất ngắn để không ăn CPU
            time.sleep(0.005)


def camera_response():
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return Response(
        stream_with_context(mjpeg_generator()),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers=headers,
        direct_passthrough=True,
    )


def single_frame_response():
    jpg = _get_latest_jpeg()
    return Response(
        jpg,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


def cleanup_camera():
    global _running, _reader_thread, _cap

    _running = False

    try:
        if _reader_thread is not None and _reader_thread.is_alive():
            _reader_thread.join(timeout=1.0)
    except Exception:
        pass

    try:
        if _cap is not None:
            _cap.release()
    except Exception:
        pass

    _reader_thread = None
    _cap = None
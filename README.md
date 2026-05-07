# Dogzilla Server

`dogzilla_server` la server chay tren robot/Raspberry Pi. Server nay nhan lenh
HTTP tu Django backend/frontend, dieu khien robot Dogzilla qua serial, stream
camera, doc joystick, va tu dong chay service voice command da tich hop tu
`MCP_Dogzilla`.

Commit o workspace goc se khong tu dong gom thay doi cua repo nay.

## Cach chay

Tu thu muc cha cua `dogzilla_server`:

```bash
python -m dogzilla_server.app
```

Mac dinh server mo:

```text
0.0.0.0:9000
```

## Entry point

File chinh:

```text
app.py
```

Khi import/chay `app.py`, server se:

1. Tao Flask app.
2. Dang ky route `/control`, `/status`, `/camera`, `/frame`.
3. Khoi tao camera reader thread.
4. Khoi tao singleton `robot`.
5. Start joystick thread neu robot serial san sang.
6. Start `MCP_Dogzilla` voice serial service.
7. Chay Flask threaded server.

## Cac module chinh

```text
app.py                 Flask app va lifecycle khoi dong
config.py              Cau hinh cong, serial, camera, attitude, voice service
robot.py               Wrapper logic dieu khien Dogzilla
DOGZILLALib.py         Thu vien serial cap thap gui packet den robot
joystick_dogzilla.py   Doc tay cam USB /dev/input/js*
camera.py              OpenCV camera capture va MJPEG stream
mcp_dogzilla.py        Voice serial command service tich hop tu MCP_Dogzilla
routes/control.py      POST /control, dispatcher lenh robot/lidar
routes/status.py       GET /status va /network
routes/camera.py       GET /camera va /frame
mcp-calculator/        MCP tool server goi lai /control
```

## API chinh

### Root

```text
GET /
GET /health
```

Tra thong tin server va health check.

### Camera

```text
GET /camera
GET /frame
```

- `/camera`: stream MJPEG.
- `/frame`: mot anh JPEG don.

### Status

```text
GET /status
GET /network
```

Tra trang thai robot, lidar, pin, firmware, pose/body state, CPU/RAM/disk/IP va
thong tin network.

### Control

```text
POST /control
```

Payload co truong `command`. Vi du:

```json
{"command": "forward", "step": 8}
{"command": "turnleft", "speed": 45}
{"command": "stop"}
{"command": "behavior", "name": "Wave_Body"}
{"command": "posture", "name": "Stand_Up"}
{"command": "lidar", "action": "start", "mode": "live_map"}
{"command": "body_adjust", "tx": 0, "ty": 0, "tz": 0, "rx": 0, "ry": 0, "rz": 0}
```

## Luong dieu khien robot

```text
Frontend
  -> Django backend
    -> dogzilla_server /control
      -> routes/control.py
        -> robot.py
          -> DOGZILLALib.py
            -> serial /dev/ttyAMA0
              -> Dogzilla robot
```

`robot.py` giu state server-side cho:

- speed mode
- gait type
- perform mode
- stabilizing mode
- Z height
- roll/pitch/yaw
- body offset sliders

Moi lenh dieu khien duoc clamp/gioi han theo `config.py` truoc khi goi thu vien
Dogzilla.

## Luong Lidar/SLAM

Khi nhan:

```json
{"command": "lidar", "action": "start"}
```

`routes/control.py` se:

1. Release serial Dogzilla de Docker/ROS co the dung tai nguyen can thiet.
2. Start Docker container `yahboom_humble`.
3. Kill cac process ROS cu trong container.
4. Launch ROS2 navigation/Cartographer.
5. Start web map service trong container tren cong 8080.
6. Probe `/state` de dam bao service san sang.

Khi lidar dang chay, cac lenh move co the duoc chuyen sang ROS topic
`/cmd_vel` thay vi goi serial Dogzilla truc tiep.

## Luong camera

`camera.py` mo camera OpenCV theo `CAMERA_INDEX`, doc frame trong thread rieng
va encode JPEG. Route `/camera` chi stream frame moi nhat, giup tranh viec moi
client tu doc camera rieng.

## Luong joystick

`robot.start_joystick()` tao daemon thread doc `/dev/input/js0`. File
`joystick_dogzilla.py` map nut va analog thanh cac lenh Dogzilla nhu move,
turn, attitude, action, pace.

## Luong voice MCP_Dogzilla

`mcp_dogzilla.py` chay background thread neu `MCP_DOGZILLA_ENABLED=1`.

Voice module gui frame serial dang:

```text
$xxx#
```

Server doc ma lenh, phat phan hoi:

```text
$Axxx#
```

Map lenh hien tai:

```text
52 -> behavior Wave_Body
19 -> go_to_point A qua service cong 8080
20 -> go_to_point B qua service cong 8080
21 -> go_to_point C qua service cong 8080
22 -> go_to_point D qua service cong 8080
```

## Debug nhanh

Kiem tra server:

```bash
curl http://<robot-ip>:9000/health
curl http://<robot-ip>:9000/status
```

Gui lenh dance:

```bash
curl -X POST http://<robot-ip>:9000/control \
  -H "Content-Type: application/json" \
  -d '{"command":"behavior","name":"Wave_Body"}'
```

Kiem tra camera:

```text
http://<robot-ip>:9000/camera
http://<robot-ip>:9000/frame
```

Neu robot khong phan hoi:

- Kiem tra `DOGZILLA_PORT`.
- Kiem tra quyen truy cap serial.
- Kiem tra Docker/ROS co dang giu serial hay khong.
- Kiem tra log `[DOGZILLA]` va `[RobotAPI]` tren terminal.

import serial

def listen_voice(port="/dev/ttyUSB0", baudrate=115200):
    ser = serial.Serial(port, baudrate, timeout=1)

    print("Dang lang nghe voice module...")

    while True:
        if ser.in_waiting:
            try:
                data = ser.readline().decode("utf-8", errors="ignore").strip()
                if data:
                    print("Nhan duoc:", data)
            except:
                pass
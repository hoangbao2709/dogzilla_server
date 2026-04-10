from Speech_Lib import Speech

spe = Speech("/dev/ttyUSB0")

while True:
    cmd = spe.speech_read()
    if cmd != 999:
        print("Detected:", cmd)
        spe.void_write(cmd)
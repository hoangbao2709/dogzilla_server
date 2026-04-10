from Speech_Lib import Speech
from command_handler import CommandHandler
from robot_control import Robot

spe = Speech("/dev/ttyUSB0")
robot = Robot()
handler = CommandHandler(robot)

while True:
    cmd = spe.speech_read()

    if cmd != 999:
        handler.handle(cmd)
        spe.void_write(cmd)  # ph?n h?i loa
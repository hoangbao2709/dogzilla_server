class CommandHandler:
    def __init__(self, robot):
        self.robot = robot

    def handle(self, cmd):
        if cmd == 4:
            print("Move forward")
            self.robot.forward()

        elif cmd == 6:
            print("Turn left")
            self.robot.turn_left()

        elif cmd == 7:
            print("Turn right")
            self.robot.turn_right()

        elif cmd == 19:
            print("Go to point A")
            self.robot.go_to_point("A")
            
        elif cmd == 52:
            print("Dancing")
            self.robot.go_to_point("A")

        else:
            print("Unknown command:", cmd)
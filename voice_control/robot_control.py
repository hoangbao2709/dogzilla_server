class Robot:
    def forward(self):
        print("[Robot] Moving forward")

    def turn_left(self):
        print("[Robot] Turning left")

    def turn_right(self):
        print("[Robot] Turning right")

    def go_to_point(self, point):
        print(f"[Robot] Navigating to point {point}")
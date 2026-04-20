#!/usr/bin/env python3
# coding: utf-8

import time
import serial


class Speech(object):
    def __init__(self, com="/dev/ttyUSB0", baudrate=115200, debug=True):
        self.debug = debug
        try:
            self.ser = serial.Serial(com, baudrate, timeout=0.1)
            if self.ser.isOpen():
                print(f"[Speech] Serial Opened! Port={com}, Baudrate={baudrate}")
        except Exception as e:
            print("[Speech] Serial Open Failed:", e)
            self.ser = None

        self.buffer = b''  

    def __del__(self):
        if self.ser and self.ser.isOpen():
            self.ser.close()
            print("[Speech] Serial Closed!")

    # =========================
    # ?? Send command (play voice)
    # =========================
    def void_write(self, void_data):
        """
        G?i l?nh ph�t �m thanh: $Axxx#
        """
        try:
            void_data = int(void_data)
            cmd = f"$A{void_data:03d}#".encode()  # format chu?n
            self.ser.write(cmd)

            if self.debug:
                print("[Speech] TX:", cmd)

            time.sleep(0.01)
            self.ser.flushInput()

        except Exception as e:
            print("[Speech] Write Error:", e)

    # =========================
    # ?? Read command (speech ? ID)
    # =========================
    def speech_read(self):
        """
        doc du lieu tu serial theo fortmat
        $xxx#
        """
        if not self.ser:
            return 999

        try:
            data = self.ser.read(64)  # d?c chunk
            if data:
                self.buffer += data

                if self.debug:
                    print("[Speech] RAW:", data)

                # t�m frame h?p l?
                while b'$' in self.buffer and b'#' in self.buffer:
                    start = self.buffer.find(b'$')
                    end = self.buffer.find(b'#', start)

                    if end == -1:
                        break

                    frame = self.buffer[start+1:end]  # l?y ph?n xxx
                    self.buffer = self.buffer[end+1:]  # c?t buffer

                    if self.debug:
                        print("[Speech] FRAME:", frame)

                    # ch? l?y s?
                    digits = ''.join(chr(c) for c in frame if chr(c).isdigit())

                    if digits:
                        cmd = int(digits)

                        if self.debug:
                            print("[Speech] CMD:", cmd)

                        return cmd

            return 999

        except Exception as e:
            print("[Speech] Read Error:", e)
            return 999
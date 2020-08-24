"""
A photobooth for the Orange Pi Lite.

Uses ffmpeg, feh, gphoto2.
"""

import atexit
from enum import Enum
import subprocess
import sys
import time

import OPi.GPIO as GPIO


class States(Enum):
    """
    The different states the photobooth might be in.
    """
    IDLE = 1,
    COUNTDOWN = 2,
    PRINT_CHECK = 3,
    SLEEP = 4,


class LED:
    """
    Handle a single GPIO powered LED.

    Keeps track of the current state in order to not spam commands.
    """
    def __init__(self, pin):
        self.pin = pin
        self.is_on = False
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, 0)

    def on(self):
        """
        Turn on the LED if necessary.
        """
        if not self.is_on:
            self.is_on = True
            GPIO.output(self.pin, 1)

    def off(self):
        """
        Turn off the LED if necessary.
        """
        if self.is_on:
            self.is_on = False
            GPIO.output(self.pin, 0)


# Bouncetime for the input, in milliseconds
BOUNCETIME = 200

# Blink cycle length, in seconds
BLINK_PERIOD = 1

# Countdown total time
COUNTDOWN_DURATION = 8

# Check print total time
PRINT_CHECK_DURATION = 10

# Time before sleep
TIME_BEFORE_SLEEP = 30


PIN_LED_BUTTON = 7
PIN_BUTTON = 15

# SEGMENTS:
#
#  AAAA
# D    B
# D    B
#  CCCC
# G    E
# G    E
#  FFFF H

PIN_SEG_DISPLAY = {
    'A':16,
    'B':18,
    'C':22,
    'D':26,
    'E':29,
    'F':31,
    'G':32,
    'H':33,
}

# State variables
#TODO use a class to store the state.
BUTTON_LED = None
CURRENT_STATE = States.SLEEP
TOTAL_TIME = 0
STATE_START = 0
CURRENT_PHOTO_PATH = None
VIDEO_FEED_POPEN = None
PHOTO_PREVIEW_POPEN = None

def kill_video_feed():
    """
    Kill the gphoto | ffmpeg video feed.
    """
    VIDEO_FEED_POPEN.terminate()
    VIDEO_FEED_POPEN.wait()


def start_video_feed():
    """
    Launch gphoto | ffmpeg in a subprocess.
    """
    global VIDEO_FEED_POPEN
    VIDEO_FEED_POPEN = subprocess.Popen(["gphoto2", "--stdout", "--capture-movie"], stdout=subprocess.PIPE)
    subprocess.Popen(["ffmpeg", "-i", "pipe:", "-pix_fmt", "yuv420p", "-tune", "zerolatency", "-preset", "ultrafast", "-f", "sdl", "-window_fullscreen", "1", "Video"], stdin=VIDEO_FEED_POPEN.stdout)


def kill_photo_preview():
    """
    Kill the feh process.
    """
    PHOTO_PREVIEW_POPEN.terminate()
    PHOTO_PREVIEW_POPEN.wait()


def start_photo_preview(path: str):
    """
    Launch feh in fullscreen in a subprocess.
    """
    global PHOTO_PREVIEW_POPEN
    PHOTO_PREVIEW_POPEN = subprocess.Popen(["feh", "-F", path])


def take_photo() -> str:
    """
    Take a photo and return the path.
    """
    photo_time = time.localtime()
    photo_path = "{}-{}_{}_{}.jpg".format(photo_time.tm_mday, photo_time.tm_hour, photo_time.tm_min, photo_time.tm_sec)
    subprocess.check_call(["gphoto2", "--capture-image-and-download", "--filename", photo_path])
    print("took photo as {}.".format(photo_path))
    return photo_path


def print_photo(path: str):
    """
    Print a photo.
    """
    #TODO print
    print("TODO PRINT PHOTO")


def button_event(_channel):
    """
    Called on a button press.

    Handles state switching, as well as print cancelling.
    """
    global CURRENT_STATE
    global TOTAL_TIME
    global STATE_START

    # Wake up from sleep
    if CURRENT_STATE == States.SLEEP:
        #TODO wake up camera
        start_video_feed()
        STATE_START = TOTAL_TIME
        CURRENT_STATE = States.IDLE
    # Start countdown
    elif CURRENT_STATE == States.IDLE:
        STATE_START = TOTAL_TIME
        CURRENT_STATE = States.COUNTDOWN
    # Cancel print by going directly to IDLE
    elif CURRENT_STATE == States.PRINT_CHECK:
        kill_photo_preview()
        start_video_feed()
        CURRENT_STATE = States.IDLE
        STATE_START = TOTAL_TIME


def init_board():
    """
    Initialize the GPIO pins and events.
    """
    global BUTTON_LED
    # Set up GPIO library
    GPIO.setboard(GPIO.PCPCPLUS) # PCPCPLUS is pinout compatible with the Lite
    GPIO.setmode(GPIO.BOARD)

    # Set up pins
    BUTTON_LED = LED(PIN_LED_BUTTON)
    GPIO.setup(PIN_BUTTON, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    for pin_number in PIN_SEG_DISPLAY.values():
        GPIO.setup(pin_number, GPIO.OUT)

    # Add button event
    GPIO.add_event_detect(PIN_BUTTON, GPIO.FALLING, callback=button_event, bouncetime=BOUNCETIME)


def update(dt):
    global TOTAL_TIME
    global STATE_START
    global CURRENT_STATE
    global CURRENT_PHOTO_PATH
    global VIDEO_FEED_POPEN

    TOTAL_TIME += dt

    if CURRENT_STATE == States.COUNTDOWN:
        if TOTAL_TIME - STATE_START > COUNTDOWN_DURATION:
            kill_video_feed()
            CURRENT_PHOTO_PATH = take_photo()
            start_photo_preview(CURRENT_PHOTO_PATH)
            STATE_START = TOTAL_TIME
            CURRENT_STATE = States.PRINT_CHECK
        else:
            #TODO update 7segments display
            pass

    elif CURRENT_STATE == States.PRINT_CHECK:
        if TOTAL_TIME - STATE_START > PRINT_CHECK_DURATION:
            kill_photo_preview()
            print_photo(CURRENT_PHOTO_PATH)
            start_video_feed()
            STATE_START = TOTAL_TIME
            CURRENT_STATE = States.IDLE

    elif CURRENT_STATE == States.IDLE:
        if TOTAL_TIME - STATE_START > TIME_BEFORE_SLEEP:
            kill_video_feed()
            #TODO put camera to sleep ?
            STATE_START = TOTAL_TIME
            CURRENT_STATE = States.SLEEP
        elif VIDEO_FEED_POPEN.poll() is not None:
            raise RuntimeError("Videofeed died unexpectedly.")

    # If in sleep, blink the button light
    if CURRENT_STATE in (States.SLEEP,):
        if TOTAL_TIME % BLINK_PERIOD > BLINK_PERIOD / 2:
            BUTTON_LED.on()
        else:
            BUTTON_LED.off()
    # If in idle or print check, keep the light on
    elif CURRENT_STATE in (States.IDLE, States.PRINT_CHECK):
        BUTTON_LED.on()
    # During the countdown, turn off the light
    else:
        BUTTON_LED.off()



def main() -> int:
    """
    The main loop.
    """
    init_board()

    last_time = time.time()

    while True:
        new_time = time.time()
        update(new_time - last_time)
        last_time = new_time
        time.sleep(0.05)
    return 0


if __name__ == '__main__':
    atexit.register(GPIO.cleanup)
    sys.exit(main())

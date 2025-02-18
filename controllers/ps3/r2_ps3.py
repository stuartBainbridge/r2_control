#!/usr/bin/python
""" PS3 Joystick controller """
from __future__ import print_function
from future import standard_library
from builtins import str
from builtins import range
import pygame
import requests
import csv
import configparser
import os
import sys
import time
import datetime
import argparse
import math
from io import StringIO
from collections import defaultdict
from SabertoothPacketSerial import SabertoothPacketSerial
from shutil import copyfile
import odrive
from odrive.enums import *
import signal
sys.path.insert(0, '/home/pi/r2_control')
from r2utils import mainconfig
standard_library.install_aliases()


def sig_handler(signal, frame):
    """ Handle signals """
    print('Cleaning Up')
    sys.exit(0)


signal.signal(signal.SIGINT, sig_handler)

##########################################################
# Load config
_configfile = mainconfig.mainconfig['config_dir'] + 'ps3.cfg'
_keysfile = mainconfig.mainconfig['config_dir'] + 'ps3_keys.csv'
_config = configparser.SafeConfigParser({'log_file': '/home/pi/r2_control/logs/ps3.log',
                                         'baseurl': 'http://localhost:5000/',
                                         'keepalive': 0.25,
                                         'speed_fac': 0.35,
                                         'invert': 1,
                                         'accel_rate': 0.025,
                                         'curve': 0.6,
                                         'deadband': 0.2})

_config.add_section('Dome')
_config.set('Dome', 'address', '129')
_config.set('Dome', 'type', 'Syren')
_config.set('Dome', 'port', '/dev/ttyUSB0')
_config.add_section('Drive')
_config.set('Drive', 'address', '128')
_config.set('Drive', 'type', 'Sabertooth')
_config.set('Drive', 'port', '/dev/ttyACM0')
_config.add_section('Axis')
_config.set('Axis', 'drive', '1')
_config.set('Axis', 'turn', '0')
_config.set('Axis', 'dome', '3')
_config.read(_configfile)

if not os.path.isfile(_configfile):
    print("Config file does not exist")
    with open(_configfile, 'wb', encoding="utf-8") as configfile:
        _config.write(configfile)

ps3config = _config.defaults()

##########################################################
# Set variables
# Log file location
log_file = ps3config['log_file']

# How often should the script send a keepalive (s)
keepalive = float(ps3config['keepalive'])

# Speed factor. This multiplier will define the max value to be sent to the drive system.
# eg. 0.5 means that the value of the joystick position will be halved
# Should never be greater than 1
speed_fac = float(ps3config['speed_fac'])

# Invert. Does the drive need to be inverted. 1 = no, -1 = yes
invert = int(ps3config['invert'])
print("Invert status: %s" % invert)

drive_mod = speed_fac * invert

# Deadband: the amount of deadband on the sticks
deadband = float(ps3config['deadband'])

# Exponential curve constant. Set this to 0 < curve < 1 to give difference response curves for axis
curve = float(ps3config['curve'])

dome_speed = 0
accel_rate = float(ps3config['accel_rate'])
dome_stick = 0

# Set Axis definitions
PS3_AXIS_LEFT_VERTICAL = int(_config.get('Axis', 'drive'))
PS3_AXIS_LEFT_HORIZONTAL = int(_config.get('Axis', 'turn'))
PS3_AXIS_RIGHT_HORIZONTAL = int(_config.get('Axis', 'dome'))

baseurl = ps3config['baseurl']

os.environ["SDL_VIDEODRIVER"] = "dummy"


################################################################################
################################################################################
# Custom Functions
def locate(user_string="PS3 Controller", x=0, y=0):
    """ Place the text at a certain location """
    # Don't allow any user errors. Python's own error detection will check for
    # syntax and concatination, etc, etc, errors.
    x = int(x)
    y = int(y)
    if x >= 80:
        x = 80
    if y >= 40:
        y = 40
    if x <= 0:
        x = 0
    if y <= 0:
        y = 0
    HORIZ = str(x)
    VERT = str(y)
    # Plot the user_string at the starting at position HORIZ, VERT...
    print("\033["+VERT+";"+HORIZ+"f"+user_string)


def steering(x, y, drive_mod):
    """ Combine Axis output to power differential drive motors """
    # convert to polar
    r = math.hypot(x, y)
    t = math.atan2(y, x)

    # rotate by 45 degrees
    t += math.pi / 4

    # back to cartesian
    left = r * math.cos(t)
    right = r * math.sin(t)

    # rescale the new coords
    left = left * math.sqrt(2)
    right = right * math.sqrt(2)

    # clamp to -1/+1
    left = (max(-1, min(left, 1)))*drive_mod
    right = (max(-1, min(right, 1)))*drive_mod

    # Send command to drives. ODrive has a max speed setting, which defines max rev/s of the motor
    # Q85s have a gear box, so this is not the speed of the actual wheel.
    if not args.dryrun:
        if _config.get('Drive', 'type') == "Sabertooth":
            drive.motor(0, left)
            drive.motor(1, right)
        elif _config.get('Drive', 'type') == "ODrive":
            drive.axis0.controller.input_vel = left*int(_config.get('Drive', 'max_vel'))
            drive.axis1.controller.input_vel = right*int(_config.get('Drive', 'max_vel'))
    if args.curses:
        # locate("                   ", 13, 11)
        # locate("                   ", 13, 12)
        locate('%10f' % left, 13, 11)
        locate('%10f' % right, 13, 12)

    return left, right


def clamp(n, minn, maxn):
    """ Clamp a number between two values """
    if n < minn:
        if __debug__:
            print("Clamping min")
        return minn
    elif n > maxn:
        if __debug__:
            print(f"Clamping max {str(n)}")
        return maxn
    else:
        return n


def shutdownR2():
    if _config.get('Drive', 'type'):
        f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                f"Axis0: {drive.axis0.error} {drive.axis0.motor.error} {drive.axis0.controller.error}\n")
        f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                f"Axis1: {drive.axis1.error} {drive.axis1.motor.error} {drive.axis1.controller.error}\n")

    """ shutdownR2 - Put R2 into a safe state """
    if __debug__:
        print("Running shutdown procedure")
    if __debug__:
        print("Stopping all motion...")
        print("...Setting drive to 0")
    steering(0, 0, drive_mod)
    print("...Setting dome to 0")
    dome.driveCommand(0)

    if __debug__:
        print("Disable drives")
    url = baseurl + "servo/body/ENABLE_DRIVE/0/0"
    try:
        requests.get(url)
    except Exception:
        print("Fail....")

    if __debug__:
        print("Disable dome")
    url = baseurl + "servo/body/ENABLE_DOME/0/0"
    try:
        requests.get(url)
    except Exception:
        print("Fail....")

    if __debug__:
        print("Bad motivator")
    # Play a sound to alert about a problem
    url = baseurl + "audio/MOTIVATR"
    try:
        requests.get(url)
    except Exception:
        print("Fail....")

    f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
            " ****** PS3 Shutdown ******\n")


parser = argparse.ArgumentParser(description='PS3 controller for r2_control.')
parser.add_argument('--curses', '-c', action="store_true", dest="curses", required=False,
                    default=False, help='Output in a nice readable format')
parser.add_argument('--dryrun', '-d', action="store_true", dest="dryrun", required=False,
                    default=False, help='Output in a nice readable format')
args = parser.parse_args()

# Open a log file
f = open(log_file, 'at')
f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
        " : ****** ps3 started ******\n")
f.flush()

while True:
    pygame.joystick.quit()
    pygame.joystick.init()
    num_joysticks = pygame.joystick.get_count()
    if __debug__:
        print(f"Waiting for joystick... (count {num_joysticks})")
    if num_joysticks != 0:
        f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                " : Joystick found \n")
        f.flush()
        break
    time.sleep(5)

if not args.dryrun:
    if __debug__:
        print("Not a drytest")
        print(f"Drive type: {_config.get('Drive', 'type')}")
    if _config.get('Drive', 'type') == "Sabertooth":
        print("**** Using Sabertooth for main drive ****")
        drive = SabertoothPacketSerial(address=int(_config.get('Drive', 'address')),
                                       type=_config.get('Drive', 'type'),
                                       port=_config.get('Drive', 'port'))
    elif _config.get('Drive', 'type') == "ODrive":
        print("***** Using ODRIVE for main drive ***** ")
        print("finding an odrive...")
        drive = odrive.find_any()  # "serial:" + _config.get('Drive', 'port'))
        drive.axis0.config.watchdog_timeout = 0.5
        drive.axis1.config.watchdog_timeout = 0.5
        drive.axis0.watchdog_feed()
        drive.axis1.watchdog_feed()
        drive.clear_errors()
        drive.clear_errors()
        drive.axis0.controller.config.input_mode = 2
        drive.axis1.controller.config.input_mode = 2
        drive.axis0.config.enable_watchdog = True
        drive.axis1.config.enable_watchdog = True
        drive.axis0.requested_state = 8
        drive.axis1.requested_state = 8
    else:
        print("No drive configured....")

    dome = SabertoothPacketSerial(address=int(_config.get('Dome', 'address')),
                                  type=_config.get('Dome', 'type'),
                                  port=_config.get('Dome', 'port'))

pygame.display.init()

if args.curses:
    print('\033c')
    locate("-=[ PS3 Controller ]=-", 10, 0)
    locate("Left", 3, 2)
    locate("Right", 30, 2)
    locate("Joystick Input", 18, 3)
    locate("Drive Value (    )", 16, 7)
    locate('%4s' % speed_fac, 29, 7)
    locate("Motor 1: ", 3, 11)
    locate("Motor 2: ", 3, 12)
    locate("Last button", 3, 13)


pygame.init()
size = (pygame.display.Info().current_w, pygame.display.Info().current_h)
if __debug__:
    print(f"Framebuffer size: {size[0]} x {size[1]}")

j = pygame.joystick.Joystick(0)
j.init()
buttons = j.get_numbuttons()

# Check theres a keys config file:
if not os.path.isfile(_keysfile):
    copyfile('keys-default.csv', _keysfile)

# Read in key combos from csv file
keys = defaultdict(list)
with open(_keysfile, mode='r', encoding="utf-8") as infile:
    reader = csv.reader(infile)
    for row in reader:
        if __debug__:
            print(f"Row: {row[0]} | {row[1]} | {row[2]}")
        keys[row[0]].append(row[1])
        keys[row[0]].append(row[2])

list(keys.items())

url = baseurl + "audio/Happy007"
try:
    r = requests.get(url)
except Exception:
    if __debug__:
        print("Fail....")

f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
        " : System Initialised \n")
f.flush()

last_command = time.time()
joystick = True

previous = ""
_throttle = 0
_turning = 0

# Main loop
while joystick:
    time.sleep(0.005)
    steering(_turning, _throttle, drive_mod)
    difference = float(time.time() - last_command)
    # Send watchdog
    if _config.get("Drive", "type") == "ODrive":
        drive.axis0.watchdog_feed()
        drive.axis1.watchdog_feed()
    if difference > keepalive:
        if os.path.exists('/dev/input/js0'):
            if __debug__:
                print("Joystick still there....")
        else:
            print("No joystick")
            joystick = False
            shutdownR2()
        # Check for no shutdown file
        if os.path.exists('/home/pi/.r2_config/.shutdown'):
            print("Shutdown file is there")
            joystick = False
            shutdownR2()
        last_command = time.time()
    try:
        events = pygame.event.get()
    except Exception:
        if __debug__:
            print("Something went wrong!")
        shutdownR2()
        sys.exit(0)
    for event in events:
        if event.type == pygame.JOYBUTTONDOWN:
            buf = StringIO()
            for i in range(buttons):
                button = j.get_button(i)
                buf.write(str(button))
            combo = buf.getvalue()
            if __debug__:
                print(f"Buttons pressed: {combo}")
            if args.curses:
                locate("                   ", 1, 14)
                locate(combo, 3, 14)
            # Special key press (All 4 plus triangle) to increase speed of drive
            if combo == "00001111000000001":
                if __debug__:
                    print("Incrementing drive speed")
                # When detected, will increment the speed_fac by 0.5 and give some audio feedback.
                speed_fac += 0.05
                if speed_fac > 1:
                    speed_fac = 1
                if __debug__:
                    print(f"*** NEW SPEED {speed_fac}")
                if args.curses:
                    locate('%4f' % speed_fac, 28, 7)
                drive_mod = speed_fac * invert
                f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                        " : Speed Increase : " + str(speed_fac) + " \n")
                url = baseurl + "audio/Happy006"
                try:
                    r = requests.get(url)
                except Exception:
                    if __debug__:
                        print("Fail....")
            # Special key press (All 4 plus X) to decrease speed of drive
            if combo == "00001111000000010":
                if __debug__:
                    print("Decrementing drive speed")
                # When detected, will increment the speed_fac by 0.5 and give some audio feedback.
                speed_fac -= 0.05
                if speed_fac < 0.2:
                    speed_fac = 0.2
                if __debug__:
                    print(f"*** NEW SPEED {speed_fac}")
                if args.curses:
                    locate('%4f' % speed_fac, 28, 7)
                drive_mod = speed_fac * invert
                f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                        " : Speed Decrease : " + str(speed_fac) + " \n")
                url = baseurl + "audio/Sad__019"
                try:
                    r = requests.get(url)
                except Exception:
                    if __debug__:
                        print("Fail....")
            # Disable Drives for odrive
            if _config.get("Drive", "type") == "ODrive":
                if combo == "00000000000100000":
                    if __debug__:
                        print("Disable ODrive")
                    drive.axis0.requested_state = 1
                    drive.axis1.requested_state = 1
                    f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                        " : Drives Disables \n")
                if combo == "00000000010000000":
                    if __debug__:
                        print("Enable ODrive")
                    drive.axis0.requested_state = 8
                    drive.axis1.requested_state = 8
                    drive.clear_errors()
                    drive.clear_errors()
                    f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                        " : Drives Enabled \n")
            try:
                newurl = baseurl + keys[combo][0]
                f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                        " : Button Down event : " + combo + "," + keys[combo][0] + " \n")
                f.flush()
                if __debug__:
                    print(f"Would run: {keys[combo]}")
                    print(f"URL: {newurl}")
                try:
                    r = requests.get(newurl)
                except Exception:
                    if __debug__:
                        print("No connection")
            except Exception:
                if __debug__:
                    print("No combo (pressed)")
            previous = combo
        if event.type == pygame.JOYBUTTONUP:
            if __debug__:
                print(f"Buttons released: {previous}")
            try:
                newurl = baseurl + keys[previous][1]
                f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                        " : Button Up event : " + previous + "," + keys[previous][1] + "\n")
                f.flush()
                if __debug__:
                    print(f"Would run: {keys[previous][1]}")
                    print(f"URL: {newurl}")
                try:
                    r = requests.get(newurl)
                except Exception:
                    if __debug__:
                        print("No connection")
            except Exception:
                if __debug__:
                    print("No combo (released)")
            previous = ""
        if event.type == pygame.JOYAXISMOTION:
            if event.axis == PS3_AXIS_LEFT_VERTICAL:
                if __debug__:
                    print(f"Value (Drive): {event.value} : Speed Factor : {speed_fac}")
                if args.curses:
                    locate("                   ", 10, 4)
                    locate('%10f' % (event.value), 10, 4)
                _throttle = event.value
                last_command = time.time()
            elif event.axis == PS3_AXIS_LEFT_HORIZONTAL:
                if __debug__:
                    print(f"Value (Steer): {event.value}")
                if args.curses:
                    locate("                   ", 10, 5)
                    locate('%10f' % (event.value), 10, 5)
                _turning = event.value
                last_command = time.time()
            elif event.axis == PS3_AXIS_RIGHT_HORIZONTAL:
                if __debug__:
                    print(f"Value (Dome): {event.value}")
                if args.curses:
                    locate("                   ", 35, 4)
                    locate('%10f' % (event.value), 35, 4)
                f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') +
                        " : Dome : " + str(event.value) + "\n")
                f.flush
                if not args.dryrun:
                    if __debug__:
                        print("Not a drytest")
                    dome.driveCommand(clamp(event.value, -0.99, 0.99))
                if args.curses:
                    locate("                   ", 35, 8)
                    locate('%10f' % (event.value), 35, 8)
                last_command = time.time()
#                dome_stick = event.value

# If the while loop quits, make sure that the motors are reset.
if __debug__:
    print("Exited main loop")
shutdownR2()

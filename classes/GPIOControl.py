import ConfigParser
import time, struct, os
import datetime
import time
import csv
import collections
import RPi.GPIO as GPIO
from config import mainconfig
from time import sleep
from flask import Blueprint, request

_configfile = 'config/gpio.cfg'

_config = ConfigParser.SafeConfigParser({'logfile': 'gpio.log', 'gpio_configfile': 'gpio_pins.cfg'})
_config.read(_configfile)

if not os.path.isfile(_configfile):
    print "Config file does not exist"
    with open(_configfile, 'wb') as configfile:
        _config.write(configfile)

_defaults = _config.defaults()

_logtofile = mainconfig['logtofile']
_logdir = mainconfig['logdir']
_logfile = _defaults['logfile']

if _logtofile:
    if __debug__:
        print "Opening log file: Dir: %s - Filename: %s" % (_logdir, _logfile)
    _f = open(_logdir + '/' + _logfile, 'at')
    _f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') + " : ****** Module Started: GPIOControl ******\n")
    _f.flush


api = Blueprint('gpio', __name__, url_prefix='/gpio')

@api.route('/<gpio>/<state>', methods=['GET'])
def _gpio_on(gpio, state):
    """ GET to set the state of a GPIO pin """
    if _logtofile:
        _f.write(datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S') + " : GPIO command : Pin: " + gpio + " State: " + state + "\n")
    message = ""
    if request.method == 'GET':
        message += _gpio.setState(gpio,state)
    return message

class _GPIOControl:

    _GPIO_def = collections.namedtuple('_GPIO_def', 'pin, name')

    def __init__(self, gpio_configfile, logdir):
        self._logdir = logdir
        self._gpio_list = []
        ifile = open('config/%s' % gpio_configfile, "rb")
        reader = csv.reader(ifile)
        GPIO.setmode(GPIO.BCM)
        for row in reader:
            pin = row[0]
            name = row[1]
            self._gpio_list.append(self._GPIO_def(pin=pin, name=name))     # Add gpio pin number and name to dictionary,
            GPIO.setup(int(row[0]), GPIO.OUT)  # Set pin as an output
            GPIO.output(int(row[0]), int(row[2]))  # Third value in csv file is default, set pin to that
        if __debug__:
            print "Initialising GPIO Control"
        self._gpio_list = dict(self._gpio_list)

    def setState(self, gpio, state):
        for gpios in self._gpio_list:
            if gpios.name == gpio:
               if __debug__:
                  print "Setting %s (pin %s) to %s" % (gpio, gpios.pin, state)
               GPIO.output(gpios.name, int(state)) 
        return "Ok"


_gpio = _GPIOControl(_defaults['gpio_configfile'],_defaults['logfile'])


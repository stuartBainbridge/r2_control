""" Module for controlling Teecees with custom firmware """
from builtins import object
import configparser
import smbus
import os
from flask import Blueprint, request
from r2utils import mainconfig
from future import standard_library
standard_library.install_aliases()


_configfile = mainconfig.mainconfig['config_dir'] + 'teecees.cfg'

_config = configparser.SafeConfigParser({'address': '0x1c', 'logfile': 'vader.log'})
_config.read(_configfile)

if not os.path.isfile(_configfile):
    print("Config file does not exist")
    with open(_configfile, 'wt', encoding="utf-8") as configfile:
        _config.write(configfile)

_defaults = _config.defaults()

_logdir = mainconfig.mainconfig['logdir']
_logfile = _defaults['logfile']

api = Blueprint('teecees', __name__, url_prefix='/teecees')


@api.route('/raw/<cmd>', methods=['GET'])
def _teecees_raw(cmd):
    """ GET to send a raw command to the teecees system"""
    message = ""
    if request.method == 'GET':
        message += _teecees.SendRaw(cmd)
    return message


@api.route('/sequence/<seq>', methods=['GET'])
def _teecees_seq(seq):
    """ GET to send a sequence command to the teecees system"""
    message = ""
    if request.method == 'GET':
        message += _teecees.SendSequence(seq)
    return message


class _TeeceesControl(object):

    def __init__(self, address, logdir):
        self.address = address
        self.bus = smbus.SMBus(int(mainconfig.mainconfig['busid']))
        self.logdir = logdir
        if __debug__:
            print("Initialising TeeCees Control")

    def SendSequence(self, seq):
        if seq.isdigit():
            if __debug__:
                print("Integer sent, sending command")
            cmd = 'S' + seq
            self.SendRaw(cmd)
        else:
            if __debug__:
                print("Not an integer, decode and send command")
            if seq == "leia":
                if __debug__:
                    print("Leia mode")
                self.SendRaw('S1')
            elif seq == "disable":
                if __debug__:
                    print("Clear and Disable")
                self.SendRaw('S8')
            elif seq == "enable":
                if __debug__:
                    print("Clear and Enable")
                self.SendRaw('S9')
        return "Ok"

    def SendRaw(self, cmd):
        array_cmd = bytearray(cmd, 'utf8')
        if __debug__:
            print(array_cmd)
        for i in array_cmd:
            if __debug__:
                print(f"Sending byte: {i} ")
            try:
                self.bus.write_byte(self.address, i)
            except Exception:
                print(f"Failed to send command to {self.address}")
        return "Ok"


_teecees = _TeeceesControl(_defaults['address'], _defaults['logfile'])

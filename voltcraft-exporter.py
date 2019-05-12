from voltcraft.pps import PPS
from prometheus_client import start_http_server, Gauge
import time
import logging
import yaml
import os
import datetime
import requests

# define default config
default_config = {
    'serialport': '/dev/ttyU0',
    'webport': 8000,
    'current_adjustment_amps': 0.1,
}

# configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s:%(funcName)s():%(lineno)i:  %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S %z',
)
logger = logging.getLogger("voltcraft-exporter.%s" % __name__)


def check_config():
    global edittime
    global config
    global default_config
    if os.stat("voltcraft-exporter.yml").st_mtime > edittime:
        logger.info("Config file updated since it was last read, re-reading...")
        fileconf, edittime = read_config()
        config = default_config
        config.update(fileconf)
        logger.debug("Running with config %s" % config)
        logger.debug("Configfile voltcraft-exporter.yml last updated %s" % edittime)

def read_config():
    try:
        with open("voltcraft-exporter.yml") as f:
            edittime = os.stat("voltcraft-exporter.yml").st_mtime
            return (yaml.safe_load(f.read()), edittime)
    except FileNotFoundError:
        return ({}, 0)

def process_request():
    global adjusttime

    # do we need to read config again?
    check_config()

    # get model - value is always 1
    model.labels(model=pps._MODEL).set(1)

    # get present output levels
    voltage_output, current_output, mode = pps.reading()
    v.set(voltage_output)
    c.set(current_output)

    # set charging mode metrics
    if mode == "CC":
        ccm.set(1)
        cvm.set(0)
    elif mode == "CV":
        ccm.set(0)
        cvm.set(1)

    # get maximum values
    voltage_max, current_max = pps.limits()
    vm.set(voltage_max)
    cm.set(current_max)

    # get preset values
    voltage_preset, current_preset = pps.preset
    vp.set(voltage_preset)
    cp.set(current_preset)

    logger.debug("Output voltage is %s V and preset voltage is %s V" % (voltage_output, voltage_preset))
    logger.debug("Output current is %s A and preset current is %s A" % (current_output, current_preset))
    logger.debug("Charging mode is %s" % mode)

    # init variable
    voltage_level = "normal"

    # do we need to lower current preset due to CV
    if mode == "CV":
        new_preset = round(current_preset-config['current_adjustment_amps'], 1)
        logger.info("Charging mode is CV, decreasing current preset by %sA to %s" % (
            config['current_adjustment_amps'],
            new_preset
        ))
        pps.current(new_preset)
        adjusttime = datetime.datetime.now()
    else:
        # do we need to adjust current based on high_voltage_limit?
        if 'high_voltage_limit' in config and voltage_output > config['high_voltage_limit']:
            new_preset = round(current_preset-config['current_adjustment_amps'], 1)
            logger.info("Voltage output %s V is over high_voltage_limit %s V, adjusting current_preset by %s A to %s A" % (
                voltage_output,
                config['high_voltage_limit'],
                config['current_adjustment_amps'],
                new_preset
            ))
            pps.current(new_preset)
            adjusttime = datetime.datetime.now()
        # do we need to adjust current based on low_voltage_limit?
        elif 'low_voltage_limit' in config and voltage_output < config['low_voltage_limit']:
            new_preset = round(current_preset+config['current_adjustment_amps'], 1)
            logger.info("Voltage output %s V is under low_voltage_limit %s V, adjusting current_preset by %s A to %s A" % (
                voltage_output,
                config['low_voltage_limit'],
                config['current_adjustment_amps'],
                new_preset
            ))
            pps.current(new_preset)
            adjusttime = datetime.datetime.now()

    logger.debug("Latest current adjustment was %s" % adjusttime)
    logger.debug("------------------------")

    time.sleep(5)

# read config file
fileconf, edittime = read_config()
config = default_config
config.update(fileconf)
logger.debug("Running with config %s" % config)
if edittime:
    # we have a configfile
    logger.debug("Configfile voltcraft-exporter.yml last updated %s" % edittime)

adjusttime = datetime.datetime.now()

# open serial connection
pps = PPS(
    port=config['serialport'],
    reset=False,
    debug=False
)


# do initial adjustment?
if 'startup_current_preset' in config or 'startup_voltage_preset' in config:
    voltage_preset, current_preset = pps.preset

if 'startup_current_preset' in config and current_preset != config['startup_current_preset']:
    logger.info("Current Preset is %s A but startup_current_preset is %s A - adjusting.." % (
        current_preset,
        config['startup_current_preset']
    ))
    pps.current(config['startup_current_preset'])

if 'startup_voltage_preset' in config and voltage_preset != config['startup_voltage_preset']:
    logger.info("Voltage Preset is %s V but startup_voltage_preset is %s V - adjusting.." % (
        voltage_preset,
        config['startup_voltage_preset']
    ))
    pps.voltage(config['startup_voltage_preset'])


# define metrics
model = Gauge('voltcraft_model', 'Voltcraft model', ['model'])
v = Gauge('voltcraft_output_voltage_volts', 'Voltcraft output voltage')
c = Gauge('voltcraft_output_current_amps', 'Voltcraft output current')
vm = Gauge('voltcraft_maximum_voltage_volts', 'Voltcraft maximum output voltage')
cm = Gauge('voltcraft_maximum_current_amps', 'Voltcraft maximum output current')
vp = Gauge('voltcraft_preset_voltage_volts', 'Voltcraft preset output voltage')
cp = Gauge('voltcraft_preset_current_amps', 'Voltcraft preset output current')
ccm = Gauge('voltcraft_mode_constant_current', 'Voltcraft power supply is in Constant Current mode')
cvm = Gauge('voltcraft_mode_constant_voltage', 'Voltcraft power supply is in Constant Voltage mode')

start_http_server(config['webport'])

while True:
    process_request()


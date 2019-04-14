from voltcraft.pps import PPS
from prometheus_client import start_http_server, Gauge
import time
import logging
import yaml
import os

# define default config
default_config = {
    'serialport': '/dev/ttyU0',
    'webport': 8000,
    'voltage_preset': 1,
    'current_preset': 1,
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
    # do we need to read config again?
    check_config()

    # get model
    model.labels(model=pps._MODEL).set(1)

    # get present output
    voltage_output, current_output, mode = pps.reading()
    v.set(voltage_output)
    c.set(current_output)

    # get charging mode
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

    # do we need to adjust voltage preset?
    if voltage_preset != config['voltage_preset']:
        logger.info("Changing voltage preset from %s to %s" % (voltage_preset, config['voltage_preset']))
        pps.voltage(config['voltage_preset'])

    # init variable
    voltage_level = "normal"

    # are we below the low_voltage_limit?
    if hasattr(config, 'low_voltage_limit') and voltage_output < config['low_voltage_limit']:
        voltage_level = "low"
        if hasattr(config, 'low_voltage_current_preset') and current_preset != config['low_voltage_current_preset']:
            logger.info("We are under the low_voltage_limit of %sV - changing current preset from %s to %s" % (config['low_voltage_limit'], current_preset, config['low_voltage_current_preset']))
            pps.current(config['low_voltage_current_preset'])

    # are we above the high_voltage_limit?
    if hasattr(config, 'high_voltage_limit') and voltage_output > config['high_voltage_limit']:
        voltage_level = "high"
        # do we need to adjust the current preset?
        if hasattr(config, 'high_voltage_current_preset') and current_preset != config['high_voltage_current_preset']:
            logger.info("We are over the high_voltage_limit of %sV - changing current preset from %s to %s" % (config['high_voltage_limit'], current_preset, config['high_voltage_current_preset']))
            pps.current(config['high_voltage_current_preset'])

    if voltage_level == "normal" and current_preset != config['current_preset']:
        logger.info("Changing current preset from %s to %s" % (current_preset, config['current_preset']))
        pps.current(config['current_preset'])

    # a bit of output for the console
    logger.debug("Output voltage is %s V and preset voltage is %s A" % (voltage_output, voltage_preset))
    logger.debug("Output current is %s V and preset current is %s A" % (current_output, current_preset))
    logger.debug("Charging mode is %s" % mode)
    logger.debug("Voltage level is %s" % voltage_level)

    time.sleep(5)

# read config file
fileconf, edittime = read_config()
config = default_config
config.update(fileconf)
logger.debug("Running with config %s" % config)
if edittime:
    logger.debug("Configfile voltcraft-exporter.yml last updated %s" % edittime)

# open serial connection
pps = PPS(
    port=config['serialport'],
    reset=False,
    debug=False
)

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


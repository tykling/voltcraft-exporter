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
    'adjustments': {},
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
    global adjusttimes

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
    if adjusttimes:
        logger.debug("Latest adjusttimes are: %s" % adjusttimes)

    for name, adjustment in config['adjustments'].items():
        # first a few sanity checks
        if not 'conditions' in adjustment:
            logger.error("adjustment %s: no conditions found, skipping" % name)
            continue

        if not 'adjustments' in adjustment:
            logger.error("adjustment %s: no adjustments found, skipping" % name)
            continue

        if not 'interval' in adjustment:
            logger.error("adjustment %s: no interval found, skipping" % name)
            continue

        # check interval
        if name in adjusttimes:
            # this adjustment has been done before, check the interval
            nextadj = adjusttimes[name] + datetime.timedelta(seconds=adjustment['interval'])
            if not nextadj < datetime.datetime.now():
                logger.debug("adjustment %s: latest adjustment was %s, next possible adjustment is %s" % (
                    name,
                    adjusttimes[name],
                    nextadj,
                ))
                continue

        if 'mode' in adjustment['conditions']:
            if not adjustment['conditions']['mode'] == mode:
                logger.debug("adjustment %s: mode condition not met: mode is %s" % (name, mode))
                continue

        if 'voltage_lt' in adjustment['conditions']:
            if not voltage_output < adjustment['conditions']['voltage_lt']:
                logger.debug("adjustment %s: voltage_lt condition not met: voltage_output is %s which is not < %s" % (
                    name,
                    voltage_output,
                    adjustment['conditions']['voltage_lt']
                ))
                continue

        if 'voltage_gt' in adjustment['conditions']:
            if not voltage_output > adjustment['conditions']['voltage_gt']:
                logger.debug("adjustment %s: voltage_gt condition not met: voltage_output is %s which is not > %s" % (
                    name,
                    voltage_output,
                    adjustment['conditions']['voltage_gt']
                ))
                continue

        if 'current_lt' in adjustment['conditions']:
            if not current_output < adjustment['conditions']['current_lt']:
                logger.debug("adjustment %s: current_lt condition not met: current_output is %s which is not < %s" % (
                    name,
                    current_output,
                    adjustment['conditions']['current_lt']
                ))
                continue

        if 'current_gt' in adjustment['conditions']:
            if not current_output > adjustment['conditions']['current_gt']:
                logger.debug("adjustment %s: current_gt condition not met: current_output is %s which is not > %s" % (
                    name,
                    current_output,
                    adjustment['conditions']['current_gt'],
                ))
                continue

        if 'prometheus' in adjustment['conditions']:
            for promadj in adjustment['conditions']['prometheus']:
                # the initial result of the prometheus conditions is False
                promok = False

                # do we have a URL
                if not 'url' in promadj:
                    logger.error("No prometheus url found, skipping this prometheus condition")
                    continue

                # do we have anything to compare with?
                if not 'lt' in promadj and not 'eq' in promadj and not 'gt' in promadj:
                    logger.error("No limits found in prometheus adjustment for url %s, skipping" % promadj['url'])
                    continue

                # get data from prometheus
                try:
                    r = requests.get(promadj['url'])
                    result = round(float(r.json()['data']['result'][0]['value'][1]), 3)
                except Exception as E:
                    logger.exception("Got exception while getting data from Prometheus url %s: %s" % (promadj['url'], E))
                    continue

                if 'lt' in promadj and not result < promadj['lt']:
                    logger.debug("adjustment %s: prometheus condition not met: url %s returned %s which is not < %s" % (
                        name,
                        promadj['url'],
                        result,
                        promadj['lt']
                    ))
                    continue

                if 'eq' in promadj and not result == promadj['eq']:
                    logger.debug("adjustment %s: prometheus condition not met: url %s returned %s which is not == %s" % (
                        name,
                        promadj['url'],
                        result,
                        promadj['eq']
                    ))
                    continue

                if 'gt' in promadj and not result < promadj['gt']:
                    logger.debug("adjustment %s: prometheus condition not met: url %s returned %s which is not > %s" % (
                        name,
                        promadj['url'],
                        result,
                        promadj['gt']
                    ))
                    continue

                # if we got this far this prometheus condition was met,
                # and if it was the last prometheus condition then True will be the final result
                promok = True

        if 'prometheus' in adjustment['conditions'] and not promok:
            # one or more prometheus conditions were checked but not met
            continue

        # if we got this far all conditions have been checked and met, do the adjustment(s)
        if 'current' in adjustment['adjustments']:
            new_preset = round(current_preset-adjustment['adjustments']['current'], 1)
            pps.current(new_preset)
            logger.info("adjustment %s: all conditions met, adjusting current_preset from %s by %s to %s" % (
                name,
                current_preset,
                adjustment['adjustments']['current'],
                new_preset,
            ))

        if 'voltage' in adjustment['adjustments']:
            new_preset = round(voltage_preset-adjustment['adjustments']['voltage'], 1)
            pps.voltage(new_preset)
            logger.info("adjustment %s: all conditions met, adjusting voltage_preset from %s by %s to %s" % (
                name,
                voltage_preset,
                adjustment['adjustments']['voltage'],
                new_preset,
            ))

        # record the time of adjustment
        adjusttimes[name] = datetime.datetime.now()

    # sleep a bit before returning
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

# init empty dict
adjusttimes = {}

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


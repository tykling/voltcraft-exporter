from voltcraft.pps import PPS
from prometheus_client import start_http_server, Summary, Gauge
import random
import time
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s:%(funcName)s():%(lineno)i:  %(message)s",
    datefmt='%Y-%m-%d %H:%M:%S %z',
)

logger = logging.getLogger("voltcraft-exporter.%s" % __name__)

pps = PPS(
    port="/dev/ttyU0",
    reset=False,
    debug=False
)

v = Gauge('voltcraft_output_voltage_volts', 'Voltcraft output voltage')
c = Gauge('voltcraft_output_current_amps', 'Voltcraft output current')
vm = Gauge('voltcraft_maximum_voltage_volts', 'Voltcraft maximum output voltage')
cm = Gauge('voltcraft_maximum_current_amps', 'Voltcraft maximum output current')
vp = Gauge('voltcraft_preset_voltage_volts', 'Voltcraft preset output voltage')
cp = Gauge('voltcraft_preset_current_amps', 'Voltcraft preset output current')
ccm = Gauge('voltcraft_mode_constant_current', 'Voltcraft power supply is in Constant Current mode')
cvm = Gauge('voltcraft_mode_constant_voltage', 'Voltcraft power supply is in Constant Voltage mode')


def process_request():
    voltage_output, current_output, mode = pps.reading()
    v.set(voltage_output)
    c.set(current_output)
    if mode == "CC":
        ccm.set(1)
        cvm.set(0)
    elif mode == "CV":
        ccm.set(0)
        cvm.set(1)

    voltage_max, current_max = pps.limits()
    vm.set(voltage_max)
    cm.set(current_max)

    voltage_preset, current_preset = pps.preset
    vp.set(voltage_preset)
    cp.set(current_preset)

    logger.debug("output voltage is %s preset voltage is %s" % (voltage_output, voltage_preset))
    logger.debug("output current is %s preset current is %s" % (current_output, current_preset))
    logger.debug("charging mode is %s" % mode)
    time.sleep(5)


start_http_server(8000)

while True:
    process_request()


import argparse
from pywayland.protocol.wayland import Seat, DataDeviceManager
from pywayland.protocol.wayland.dataoffer import DataOffer
from pywayland.client.display import Display
import pywayland
import logging
from logging import debug, error, info
from os import fork
from sys import exit

class WaylandContext():
    class SelectionChanged(Exception):
        pass

    def _registry_handler(self, wl_registry, id, iface_name, version):
        if iface_name == "wl_data_device_manager":
            debug("Found wl_data_device_manager v%d" % version)
            self.data_device_manager = wl_registry.bind(id, DataDeviceManager, version)
        elif iface_name == "wl_seat":
            debug("Found wl_seat v%d" % version)
            self.seat = wl_registry.bind(id, Seat, version)

    def __init__(self):
        self._cancelled_count = 0

        debug("Connecting to wayland display")
        self.display = Display()
        self.display.connect()

        debug("Getting global registry")
        self.registry = self.display.get_registry()
        self.registry.dispatcher['global'] = self._registry_handler
        self.display.dispatch()
        self.display.roundtrip()

        if not hasattr(self, 'data_device_manager'):
            raise Exception("No data device manager provided by compositor")

        self.data_device = self.data_device_manager.get_data_device(self.seat)

    def _serial_cb(self, callback, serial):
        self._serial = serial

    def _get_new_serial(self):
        cb = self.display.sync()
        cb.dispatcher['done'] = self._serial_cb
        self.display.roundtrip()

        serial = self._serial
        del self._serial
        return serial

    def _send_handler(self, data_source, mime_type, fd):
        self._cancelled_count = 0

        debug("Received fd %d for mime_type '%s'" % (fd, mime_type))
        self._send_args = (mime_type, fd)

    def _cancelled_handler(self, data_source):
        self._cancelled_count += 1
        # Two cancels in a row seems to indicate the selection actually changed
        if self._cancelled_count == 2:
            self._send_args = WaylandContext.SelectionChanged()

    def create_data_source(self, mime_types):
        debug("Creating data source")
        self.data_source = self.data_device_manager.create_data_source()
        self.data_source.dispatcher['send'] = self._send_handler
        self.data_source.dispatcher['cancelled'] = self._cancelled_handler

        for mime_type in mime_types:
            debug("Offering mime type '%s'" % mime_type)
            self.data_source.offer(mime_type)

        serial = self._get_new_serial()
        self.data_device.set_selection(self.data_source, serial)
        self.display.roundtrip()

    def wait_for_paste(self):
        debug("Waiting for paste events...")
        while not hasattr(self, '_send_args'):
            self.display.dispatch()

        # For some silly reason we can't raise exceptions from callbacks, so
        # just pass them through self._send_args
        if isinstance(self._send_args, Exception):
            raise self._send_args

        ret = self._send_args
        del self._send_args
        return ret

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog='waypaste',
                                     description="A CLI interface to copy from Wayland applications")
    parser.add_argument('source', help='The source to copy from',
                        default='/dev/stdin');
    parser.add_argument('--verbose', '-v', help='Be louder', action='store_const',
                        dest='loglevel', const=logging.DEBUG, default=logging.INFO)

    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel)

    ctx = WaylandContext()

    # STRING and TEXT definitely aren't mime types, but some applications seem
    # to need them before they acknowledge anything on the clipboard
    ctx.create_data_source([
        'text/plain',
        'STRING',
        'TEXT',
    ])

    data_source = open(args.source, "rb")
    if not data_source.seekable():
        paste_data = data_source.read()

    while True:
        try:
            mime_type, fd = ctx.wait_for_paste()

            debug("Sending data")
            if data_source.seekable():
                data_source.seek(0)
                paste_data = data_source.read()

            open(fd, "wb").write(paste_data)
        except WaylandContext.SelectionChanged:
            break

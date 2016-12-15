# Copyright ©2016 Lyude Paul <thatslyude@gmail.com>
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; version 2.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import argparse
from pywayland.protocol.wayland import Seat, DataDeviceManager
from pywayland.protocol.wayland.dataoffer import DataOffer
from pywayland.client.display import Display
from threading import Thread
import logging
from logging import debug, error, info
from os import fork, O_NONBLOCK, _exit, environ
from sys import stderr, exit
import fcntl
from waypaste.version import __version__

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
        try:
            debug("Connecting to wayland display")
            self.display = Display()
            self.display.connect()
        except Exception as e:
            if 'WAYLAND_DISPLAY' not in environ or \
               environ['WAYLAND_DISPLAY'] == '':
                raise Exception("WAYLAND_DISPLAY is not set") from e
            else:
                raise e from e

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
        debug("Selection changed, exiting")
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

# We run the wayland dispatch loop in a seperate thread so that we can still
# handle signals like SIGINT
class MainThread(Thread):
    def __init__(self, ctx, data_source, paste_data):
        super().__init__()
        self.ctx = ctx
        self.data_source = data_source
        self.paste_data = paste_data
        self.daemon = True

    def run(self):
        while True:
            try:
                mime_type, fd = self.ctx.wait_for_paste()

                debug("Sending data")
                if self.data_source.seekable():
                    self.data_source.seek(0)
                    paste_data = self.data_source.read()
                else:
                    paste_data = self.paste_data

                with open(fd, "wb") as out:
                    # Set the file descriptor as blocking
                    fcntl.fcntl(out, fcntl.F_SETFL,
                                fcntl.fcntl(out, fcntl.F_GETFL) & ~O_NONBLOCK)
                    out.write(paste_data)
            except WaylandContext.SelectionChanged:
                break

def main():
    parser = argparse.ArgumentParser(
        prog='waypaste',
        description="A CLI interface to set the clipboard contents of wayland applications."
    )
    parser.add_argument('--version', '-V', action='version',
                        version=__version__)
    parser.add_argument('source', help='The source to copy from',
                        default='/dev/stdin', nargs='?');
    parser.add_argument('--verbose', '-v', help='Be louder', action='store_const',
                        dest='loglevel', const=logging.DEBUG, default=logging.INFO)
    parser.add_argument('--foreground', '-f',
                        help='Don\'t fork into the background after beginning to host clipboard data',
                        action='store_true')

    args = parser.parse_args()
    logging.basicConfig(level=args.loglevel)

    try:
        ctx = WaylandContext()
    except Exception as e:
        stderr.write("Failed to connect to wayland display: %s\n" % e.args)
        exit(1)

    # STRING and TEXT definitely aren't mime types, but some applications seem
    # to need them before they acknowledge anything on the clipboard
    ctx.create_data_source([
        'UTF8_STRING',
        'COMPOUND_TEXT',
        'TEXT',
        'STRING',
        'text/plain',
        'text/plain;charset=utf-8',
    ])

    data_source = open(args.source, "rb")
    if not data_source.seekable():
        paste_data = data_source.read()
    else:
        paste_data = None

    if not args.foreground:
        # Fork from the command line
        if fork() != 0:
            debug("Forked into the background, exiting")
            _exit(0)

    try:
        main_thread = MainThread(ctx, data_source, paste_data)
        main_thread.start()
        main_thread.join()
    except KeyboardInterrupt:
        print("Received ^C, exiting")

if __name__ == "__main__":
    main()

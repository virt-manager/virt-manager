# Copyright (C) 2006, 2013 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

# pylint: disable=wrong-import-order,ungrouped-imports
import gi
from gi.repository import Gdk
from gi.repository import Gtk

from virtinst import log

# We can use either 2.91 or 2.90. This is just to silence runtime warnings
try:
    gi.require_version("Vte", "2.91")
    log.debug("Using VTE API 2.91")
except ValueError:  # pragma: no cover
    gi.require_version("Vte", "2.90")
    log.debug("Using VTE API 2.90")
from gi.repository import Vte

import libvirt

from ..baseclass import vmmGObject


class _DataStream(vmmGObject):
    """
    Wrapper class for interacting with libvirt console stream
    """
    def __init__(self, vm):
        vmmGObject.__init__(self)

        self.vm = vm
        self.conn = vm.conn

        self._stream = None

        self._streamToTerminal = b""
        self._terminalToStream = ""

    def _cleanup(self):
        self.close()

        self.vm = None
        self.conn = None


    #################
    # Internal APIs #
    #################

    def _display_data(self, terminal):
        if not self._streamToTerminal:
            return  # pragma: no cover

        terminal.feed(self._streamToTerminal)
        self._streamToTerminal = b""

    def _event_on_stream(self, stream, events, opaque):
        ignore = stream
        terminal = opaque

        if (events & libvirt.VIR_EVENT_HANDLE_ERROR or
            events & libvirt.VIR_EVENT_HANDLE_HANGUP):  # pragma: no cover
            log.debug("Received stream ERROR/HANGUP, closing console")
            self.close()
            return

        if events & libvirt.VIR_EVENT_HANDLE_READABLE:
            try:
                got = self._stream.recv(1024 * 100)
            except Exception:  # pragma: no cover
                log.exception("Error receiving stream data")
                self.close()
                return

            if got == -2:  # pragma: no cover
                # This is basically EAGAIN
                return
            if len(got) == 0:
                log.debug("Received EOF from stream, closing")
                self.close()
                return

            queued_text = bool(self._streamToTerminal)
            self._streamToTerminal += got
            if not queued_text:
                self.idle_add(self._display_data, terminal)

        if (events & libvirt.VIR_EVENT_HANDLE_WRITABLE and
            self._terminalToStream):

            try:
                done = self._stream.send(self._terminalToStream.encode())
            except Exception:  # pragma: no cover
                log.exception("Error sending stream data")
                self.close()
                return

            if done == -2:  # pragma: no cover
                # This is basically EAGAIN
                return

            self._terminalToStream = self._terminalToStream[done:]

        if not self._terminalToStream:
            self._stream.eventUpdateCallback(libvirt.VIR_STREAM_EVENT_READABLE |
                                            libvirt.VIR_STREAM_EVENT_ERROR |
                                            libvirt.VIR_STREAM_EVENT_HANGUP)


    ##############
    # Public API #
    ##############

    def open(self, dev, terminal):
        if self._stream:
            return

        name = dev and dev.alias.name or None
        log.debug("Opening console stream for dev=%s alias=%s",
                      dev, name)
        # libxl doesn't set aliases, their open_console just defaults to
        # opening the first console device, so don't force prescence of
        # an alias

        stream = self.conn.get_backend().newStream(libvirt.VIR_STREAM_NONBLOCK)
        self.vm.open_console(name, stream)
        self._stream = stream

        self._stream.eventAddCallback((libvirt.VIR_STREAM_EVENT_READABLE |
                                      libvirt.VIR_STREAM_EVENT_ERROR |
                                      libvirt.VIR_STREAM_EVENT_HANGUP),
                                     self._event_on_stream,
                                     terminal)

    def close(self):
        if self._stream:
            try:
                self._stream.eventRemoveCallback()
            except Exception:  # pragma: no cover
                log.exception("Error removing stream callback")
            try:
                self._stream.finish()
            except Exception:  # pragma: no cover
                log.exception("Error finishing stream")

        self._stream = None

    def send_data(self, src, text, length, terminal):
        """
        Callback when data has been entered into VTE terminal
        """
        ignore = src
        ignore = length
        ignore = terminal

        if self._stream is None:
            return  # pragma: no cover

        self._terminalToStream += text
        if self._terminalToStream:
            self._stream.eventUpdateCallback(libvirt.VIR_STREAM_EVENT_READABLE |
                                            libvirt.VIR_STREAM_EVENT_WRITABLE |
                                            libvirt.VIR_STREAM_EVENT_ERROR |
                                            libvirt.VIR_STREAM_EVENT_HANGUP)


class vmmSerialConsole(vmmGObject):
    @staticmethod
    def can_connect(_vm, dev):
        """
        Check if we think we can actually open passed console/serial dev
        """
        usable_types = ["pty"]
        ctype = dev.type

        err = ""

        if ctype not in usable_types:
            err = (_("Console for device type '%s' is not supported") % ctype)

        return err

    @staticmethod
    def get_serialcon_devices(vm):
        serials = vm.xmlobj.devices.serial
        consoles = vm.xmlobj.devices.console
        if serials and vm.serial_is_console_dup(serials[0]):
            consoles.pop(0)
        return serials + consoles


    def __init__(self, vm, target_port, name):
        vmmGObject.__init__(self)

        self.vm = vm
        self.target_port = target_port
        self.name = name
        self.lastpath = None

        self._datastream = _DataStream(self.vm)

        self._serial_popup = None
        self._serial_copy = None
        self._serial_paste = None
        self._init_popup()

        self._vteterminal = None
        self._init_terminal()

        self._box = None
        self._error_label = None
        self._init_ui()

        self.vm.connect("state-changed", self._vm_status_changed)

    def _cleanup(self):
        self._datastream.cleanup()
        self._datastream = None

        self.vm = None
        self._vteterminal = None
        self._box = None


    ###########
    # UI init #
    ###########

    def _init_terminal(self):
        self._vteterminal = Vte.Terminal()
        self._vteterminal.set_scrollback_lines(1000)
        self._vteterminal.set_audible_bell(False)
        self._vteterminal.get_accessible().set_name("Serial Terminal")

        self._vteterminal.connect("button-press-event",
                self._show_serial_rcpopup)
        self._vteterminal.connect("commit",
                self._datastream.send_data, self._vteterminal)
        self._vteterminal.show()

    def _init_popup(self):
        self._serial_popup = Gtk.Menu()
        self._serial_popup.get_accessible().set_name("serial-popup-menu")

        self._serial_copy = Gtk.MenuItem.new_with_mnemonic(_("_Copy"))
        self._serial_copy.connect("activate", self._serial_copy_text)
        self._serial_popup.add(self._serial_copy)

        self._serial_paste = Gtk.MenuItem.new_with_mnemonic(_("_Paste"))
        self._serial_paste.connect("activate", self._serial_paste_text)
        self._serial_popup.add(self._serial_paste)

    def _init_ui(self):
        self._box = Gtk.Notebook()
        self._box.set_show_tabs(False)
        self._box.set_show_border(False)

        align = Gtk.Box()
        align.set_border_width(2)
        evbox = Gtk.EventBox()
        evbox.modify_bg(Gtk.StateType.NORMAL, Gdk.Color(0, 0, 0))
        terminalbox = Gtk.HBox()
        scrollbar = Gtk.VScrollbar()
        self._error_label = Gtk.Label()
        self._error_label.set_width_chars(40)
        self._error_label.set_line_wrap(True)

        if self._vteterminal:
            scrollbar.set_adjustment(self._vteterminal.get_vadjustment())
            align.pack_start(self._vteterminal, True, True, 0)

        evbox.add(align)
        terminalbox.pack_start(evbox, True, True, 0)
        terminalbox.pack_start(scrollbar, False, False, 0)

        self._box.append_page(terminalbox, Gtk.Label(""))
        self._box.append_page(self._error_label, Gtk.Label(""))
        self._box.show_all()

        scrollbar.hide()
        scrollbar.get_adjustment().connect(
            "changed", self._scrollbar_adjustment_changed, scrollbar)


    ###################
    # Private methods #
    ###################

    def _show_error(self, msg):
        self._error_label.set_markup("<b>%s</b>" % msg)
        self._box.set_current_page(1)

    def _lookup_dev(self):
        devs = vmmSerialConsole.get_serialcon_devices(self.vm)
        found = None
        for dev in devs:
            port = dev.get_xml_idx()
            path = dev.source.path

            if port == self.target_port:
                if path != self.lastpath:
                    log.debug("Serial console '%s' path changed to %s",
                                  self.target_port, path)
                self.lastpath = path
                found = dev
                break

        if not found:  # pragma: no cover
            log.debug("No devices found for serial target port '%s'",
                      self.target_port)
            self.lastpath = None
        return found


    ##############
    # Public API #
    ##############

    def close(self):
        if self._datastream:
            self._datastream.close()

    def get_box(self):
        return self._box

    def has_focus(self):
        return bool(self._vteterminal and
                    self._vteterminal.get_property("has-focus"))

    def set_focus_callbacks(self, in_cb, out_cb):
        self._vteterminal.connect("focus-in-event", in_cb)
        self._vteterminal.connect("focus-out-event", out_cb)

    def open_console(self):
        try:
            dev = self._lookup_dev()
            self._datastream.open(dev, self._vteterminal)
            self._box.set_current_page(0)
            return True
        except Exception as e:
            log.exception("Error opening serial console")
            self._show_error(_("Error connecting to text console: %s") % e)
            try:
                self._datastream.close()
            except Exception:  # pragma: no cover
                pass
        return False


    ################
    # UI listeners #
    ################

    def _vm_status_changed(self, vm):
        if vm.status() in [libvirt.VIR_DOMAIN_RUNNING]:
            self.open_console()
        else:
            self._datastream.close()

    def _scrollbar_adjustment_changed(self, adjustment, scrollbar):
        scrollbar.set_visible(
            adjustment.get_upper() > adjustment.get_page_size())

    def _show_serial_rcpopup(self, src, event):
        if event.button != 3:
            return

        self._serial_popup.show_all()

        if src.get_has_selection():
            self._serial_copy.set_sensitive(True)
        else:
            self._serial_copy.set_sensitive(False)
        self._serial_popup.popup_at_pointer(event)

    def _serial_copy_text(self, src_ignore):
        self._vteterminal.copy_clipboard()

    def _serial_paste_text(self, src_ignore):
        self._vteterminal.paste_clipboard()

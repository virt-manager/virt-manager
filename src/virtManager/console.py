#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Daniel P. Berrange <berrange@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#

import gobject
import cairo
import gtk.glade
import libvirt
import sys
import logging
import dbus

from vncViewer.vnc import GRFBViewer

class vmmConsole(gobject.GObject):
    __gsignals__ = {
        "action-show-details": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-show-terminal": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str,str)),
        "action-save-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str)),
        "action-destroy-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str))
        }
    def __init__(self, config, vm):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_dir() + "/vmm-console.glade", "vmm-console", domain="virt-manager")
        self.config = config
        self.vm = vm

        topwin = self.window.get_widget("vmm-console")
        topwin.hide()
        self.title = vm.get_name() + " " + topwin.get_title()
        topwin.set_title(self.title)
        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_shutdown.png")

        if self.config.get_console_keygrab() == 2:
            self.vncViewer = GRFBViewer(topwin, autograbkey=True)
        else:
            self.vncViewer = GRFBViewer(topwin, autograbkey=False)
        self.vncViewer.connect("pointer-grabbed", self.notify_grabbed)
        self.vncViewer.connect("pointer-ungrabbed", self.notify_ungrabbed)

        self.window.get_widget("console-vnc-align").add(self.vncViewer)
        self.vncViewer.connect("size-request", self.autosize)
        self.vncViewer.show()
        self.vncViewerFailures = 0
        self.vncViewerRetryDelay = 125

        self.window.get_widget("console-pages").set_show_tabs(False)

        self.config.on_console_keygrab_changed(self.keygrab_changed)

        self.ignorePause = False

        self.window.signal_autoconnect({
            "on_vmm_console_delete_event": self.close,

            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,

            "on_menu_vm_run_activate": self.control_vm_run,
            "on_menu_vm_shutdown_activate": self.control_vm_shutdown,
            "on_menu_vm_pause_activate": self.control_vm_pause,
            "on_menu_vm_save_activate": self.control_vm_save_domain,
            "on_menu_vm_destroy_activate": self.control_vm_destroy,
            "on_menu_vm_screenshot_activate": self.control_vm_screenshot,

            "on_menu_view_serial_activate": self.control_vm_terminal,
            "on_menu_view_details_activate": self.control_vm_details,
            "on_menu_view_fullscreen_activate": self.toggle_fullscreen,
            "on_menu_view_toolbar_activate": self.toggle_toolbar,

            "on_menu_vm_close_activate": self.close,

            "on_console_auth_login_clicked": self.try_login,
            })

        self.vm.connect("status-changed", self.update_widget_states)

        self.vncViewer.connect("disconnected", self._vnc_disconnected)

    # Auto-increase the window size to fit the console - within reason
    # though, cos we don't want a min window size greater than the screen
    # the user has scrollbars anyway if they want it smaller / it can't fit
    def autosize(self, src, size):
        rootWidth = gtk.gdk.screen_width()
        rootHeight = gtk.gdk.screen_height()

        vncWidth, vncHeight = src.get_size_request()

        if vncWidth > (rootWidth-200):
            vncWidth = rootWidth - 200
        if vncHeight > (rootHeight-200):
            vncHeight = rootHeight - 200

        self.window.get_widget("console-vnc-vp").set_size_request(vncWidth+2, vncHeight+2)

    def notify_grabbed(self, src):
        topwin = self.window.get_widget("vmm-console")
        try:
            bus = dbus.SessionBus()
            noteSvr = bus.get_object("org.freedesktop.Notifications", "/org/freedesktop/Notifications")
            noteObj = dbus.Interface(noteSvr, "org.freedesktop.Notifications")
            (x, y) = topwin.window.get_origin()
            noteObj.Notify(topwin.get_title(),
                           0,
                           '',
                           _("Pointer grabbed"),
                           _("The mouse pointer has been restricted to the virtual " \
                             "console window. To release the pointer press the key pair " \
                             "Ctrl+Alt"),
                           [],
                           {"desktop-entry": "virt-manager",
                            "x": x+200, "y": y},
                           5 * 1000);
        except Exception, e:
            pass
        topwin.set_title(_("Press Ctrl+Alt to release pointer.") + " " + self.title)

    def notify_ungrabbed(self, src):
        topwin = self.window.get_widget("vmm-console")
        topwin.set_title(self.title)

    def keygrab_changed(self, src, ignore1=None,ignore2=None,ignore3=None):
        if self.config.get_console_keygrab() == 2:
            self.vncViewer.set_autograb_keyboard(True)
        else:
            self.vncViewer.set_autograb_keyboard(False)

    def toggle_fullscreen(self, src):
        if src.get_active():
            self.window.get_widget("vmm-console").fullscreen()
            if self.config.get_console_keygrab() == 1:
                self.vncViewer.grab_keyboard()
        else:
            if self.config.get_console_keygrab() == 1:
                self.vncViewer.ungrab_keyboard()
            self.window.get_widget("vmm-console").unfullscreen()

    def toggle_toolbar(self, src):
        if src.get_active():
            self.window.get_widget("console-toolbar").show()
        else:
            self.window.get_widget("console-toolbar").hide()

    def show(self):
        dialog = self.window.get_widget("vmm-console")
        dialog.show_all()
        dialog.present()

        self.try_login()
        self.update_widget_states(self.vm, self.vm.status())

    def close(self,ignore1=None,ignore2=None):
        fs = self.window.get_widget("menu-view-fullscreen")
        if fs.get_active():
            fs.set_active(False)

        self.window.get_widget("vmm-console").hide()
        if self.vncViewer.is_connected():
	    try:
                self.vncViewer.disconnect_from_host()
	    except:
		logging.error("Failure when disconnecting from VNC server")
        return 1

    def is_visible(self):
        if self.window.get_widget("vmm-console").flags() & gtk.VISIBLE:
           return 1
        return 0

    def _vnc_disconnected(self, src):
        self.try_login()

    def retry_login(self):
        self.try_login()
        return False

    def try_login(self, src=None):
        if self.vm.get_id() == 0:
            return

        password = self.window.get_widget("console-auth-password").get_text()
        protocol, host, port = self.vm.get_graphics_console()

        if protocol is None:
            logging.debug("No graphics configured in guest")
            return

        uri = str(protocol) + "://" + str(host) + ":" + str(port)
        logging.debug("Graphics console configured at " + uri)

        if protocol != "vnc":
            self.activate_unavailable_page()
            return

        if not(self.vncViewer.is_connected()):
	    try:
                self.vncViewer.connect_to_host(host, port)
	    except:
                self.vncViewerFailures = self.vncViewerFailures + 1
                logging.warn("Unable to activate console " + uri + ": " + str((sys.exc_info())[0]) + " " + str((sys.exc_info())[1]))
                self.activate_unavailable_page()
                if self.vncViewerFailures < 10:
                    logging.warn("Retrying connection in %d ms", self.vncViewerRetryDelay)
                    gobject.timeout_add(self.vncViewerRetryDelay, self.retry_login)
                    if self.vncViewerRetryDelay < 2000:
                        self.vncViewerRetryDelay = self.vncViewerRetryDelay * 2
                else:
                    logging.error("Too many connection failures, not retrying again")
		return

        # Had a succesfull connect, so reset counters now
        self.vncViewerFailures = 0
        self.vncViewerRetryDelay = 125

        if self.vncViewer.is_authenticated():
            self.activate_viewer_page()
        elif password or not(self.vncViewer.needs_password()):
            if self.vncViewer.authenticate(password) == 1:
                if self.window.get_widget("console-auth-remember").get_active():
                    self.config.set_console_password(self.vm, password)
                else:
                    self.config.clear_console_password(self.vm)
                self.activate_viewer_page()
                self.vncViewer.activate()
            else:
                # Our VNC console doesn't like it when password is
                # wrong and gets out of sync in its state machine
                # So we force disconnect
                self.vncViewer.disconnect_from_host()
                self.activate_auth_page()
        else:
            self.activate_auth_page()


    def activate_unavailable_page(self):
        self.window.get_widget("console-pages").set_current_page(0)
        self.window.get_widget("menu-vm-screenshot").set_sensitive(False)

    def activate_screenshot_page(self):
        self.window.get_widget("console-pages").set_current_page(1)
        self.window.get_widget("menu-vm-screenshot").set_sensitive(True)

    def activate_auth_page(self):
        pw = self.config.get_console_password(self.vm)
        self.window.get_widget("menu-vm-screenshot").set_sensitive(False)
        self.window.get_widget("console-auth-password").set_text(pw)
        self.window.get_widget("console-auth-password").grab_focus()
        if self.config.has_keyring():
            self.window.get_widget("console-auth-remember").set_sensitive(True)
            if pw != None and pw != "":
                self.window.get_widget("console-auth-remember").set_active(True)
            else:
                self.window.get_widget("console-auth-remember").set_active(False)
        else:
            self.window.get_widget("console-auth-remember").set_sensitive(False)
        self.window.get_widget("console-pages").set_current_page(2)

    def activate_viewer_page(self):
        self.window.get_widget("console-pages").set_current_page(3)
        self.window.get_widget("menu-vm-screenshot").set_sensitive(True)
        self.vncViewer.grab_focus()

    def control_vm_screenshot(self, src):
        # If someone feels kind they could extend this code to allow
        # user to choose what image format they'd like to save in....
        fcdialog = gtk.FileChooserDialog(_("Save Virtual Machine Screenshot"),
                                         self.window.get_widget("vmm-console"),
                                         gtk.FILE_CHOOSER_ACTION_SAVE,
                                         (gtk.STOCK_CANCEL, gtk.RESPONSE_CANCEL,
                                          gtk.STOCK_SAVE, gtk.RESPONSE_ACCEPT),
                                         None)
        png = gtk.FileFilter()
        png.set_name("PNG files")
        png.add_pattern("*.png")
        fcdialog.add_filter(png)
        fcdialog.set_do_overwrite_confirmation(True)
        if fcdialog.run() == gtk.RESPONSE_ACCEPT:
            fcdialog.hide()
            file = fcdialog.get_filename()
            if not(file.endswith(".png")):
                file = file + ".png"
            screenshot = self.vncViewer.take_screenshot()
            width, height = screenshot.get_size()
            image = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB, False, 8,
                                   width, height)
            image.get_from_drawable(screenshot,
                                    gtk.gdk.colormap_get_system(),
                                    0, 0, 0, 0, width, height)

            # Save along with a little metadata about us & the domain
            image.save(file, 'png', { 'tEXt::Hypervisor URI': self.vm.get_connection().get_uri(),
                                      'tEXt::Domain Name': self.vm.get_name(),
                                      'tEXt::Domain UUID': self.vm.get_uuid(),
                                      'tEXt::Generator App': self.config.get_appname(),
                                      'tEXt::Generator Version': self.config.get_appversion() })
            msg = gtk.MessageDialog(self.window.get_widget("vmm-console"),
                                    gtk.DIALOG_MODAL,
                                    gtk.MESSAGE_INFO,
                                    gtk.BUTTONS_OK,_("The screenshot has been saved to:\n%s") % file)
            msg.set_title(_("Screenshot saved"))
            msg.run()
            msg.destroy()
        else:
            fcdialog.hide()
        fcdialog.destroy()

    def control_vm_run(self, src):
        status = self.vm.status()
        if status != libvirt.VIR_DOMAIN_SHUTOFF:
            pass
        else:
            self.vm.startup()


    def control_vm_shutdown(self, src):
        status = self.vm.status()
        if not(status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]):
            self.vm.shutdown()
        else:
            logging.warning("Shutdown requested, but machine is already shutting down / shutoff")

    def control_vm_pause(self, src):
        if self.ignorePause:
            return

        status = self.vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            logging.warning("Pause/resume requested, but machine is shutdown / shutoff")
        else:
            if status in [ libvirt.VIR_DOMAIN_PAUSED ]:
                if not src.get_active():
                    self.vm.resume()
                else:
                    logging.warning("Pause requested, but machine is already paused")
            else:
                if src.get_active():
                    self.vm.suspend()
                else:
                    logging.warning("Resume requested, but machine is already running")

        self.window.get_widget("control-pause").set_active(src.get_active())
        self.window.get_widget("menu-vm-pause").set_active(src.get_active())

    def control_vm_terminal(self, src):
        self.emit("action-show-terminal", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_save_domain(self, src):
        self.emit("action-save-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_destroy(self, src):
        self.emit("action-destroy-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_details(self, src):
        self.emit("action-show-details", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def update_widget_states(self, vm, status):
        self.ignorePause = True
        if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            self.window.get_widget("control-run").set_sensitive(True)
            self.window.get_widget("menu-vm-run").set_sensitive(True)
        else:
            self.window.get_widget("control-run").set_sensitive(False)
            self.window.get_widget("menu-vm-run").set_sensitive(False)

        if vm.is_serial_console_tty_accessible():
            self.window.get_widget("menu-view-serial").set_sensitive(True)
        else:
            self.window.get_widget("menu-view-serial").set_sensitive(False)

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF ] or vm.is_read_only():
            # apologies for the spaghetti, but the destroy choice is a special case
            self.window.get_widget("menu-vm-destroy").set_sensitive(False)
        else:
            self.window.get_widget("menu-vm-destroy").set_sensitive(True)

        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF ,libvirt.VIR_DOMAIN_CRASHED ] or vm.is_read_only():
            self.window.get_widget("control-pause").set_sensitive(False)
            self.window.get_widget("control-shutdown").set_sensitive(False)
            self.window.get_widget("menu-vm-pause").set_sensitive(False)
            self.window.get_widget("menu-vm-shutdown").set_sensitive(False)
            self.window.get_widget("menu-vm-save").set_sensitive(False)
        else:
            self.window.get_widget("control-pause").set_sensitive(True)
            self.window.get_widget("control-shutdown").set_sensitive(True)
            self.window.get_widget("menu-vm-pause").set_sensitive(True)
            self.window.get_widget("menu-vm-shutdown").set_sensitive(True)
            self.window.get_widget("menu-vm-save").set_sensitive(True)
            if status == libvirt.VIR_DOMAIN_PAUSED:
                self.window.get_widget("control-pause").set_active(True)
                self.window.get_widget("menu-vm-pause").set_active(True)
            else:
                self.window.get_widget("control-pause").set_active(False)
                self.window.get_widget("menu-vm-pause").set_active(False)

        if status in [ libvirt.VIR_DOMAIN_SHUTOFF ,libvirt.VIR_DOMAIN_CRASHED ] or vm.is_management_domain():
            self.window.get_widget("console-pages").set_current_page(0)
        else:
            if status == libvirt.VIR_DOMAIN_PAUSED:
                screenshot = None
                if self.vncViewer.is_authenticated():
                    screenshot = self.vncViewer.take_screenshot()
                if screenshot != None:
                    cr = screenshot.cairo_create()
                    width, height = screenshot.get_size()

                    # Set 50% gray overlayed
                    cr.set_source_rgba(0, 0, 0, 0.5)
                    cr.rectangle(0, 0, width, height)
                    cr.fill()

                    # Render a big text 'paused' across it
                    cr.set_source_rgba(1, 1,1, 1)
                    cr.set_font_size(80)
                    cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                    overlay = _("paused")
                    extents = cr.text_extents(overlay)
                    x = width/2 - (extents[2]/2)
                    y = height/2 - (extents[3]/2)
                    cr.move_to(x, y)
                    cr.show_text(overlay)
                    self.window.get_widget("console-screenshot").set_from_pixmap(screenshot, None)
                    self.activate_screenshot_page()
                else:
                    self.activate_unavailable_page()
            else:
                # State changed, so better let it try connecting again
                self.vncViewerFailures = 0
                self.vncViewerRetryDelay = 125
                try:
                    self.try_login()
                except:
                    logging.error("Couldn't open console " + str(sys.exc_info()[0]) + " " + str(sys.exc_info()[1]))
                    self.ignorePause = False
        self.ignorePause = False

gobject.type_register(vmmConsole)

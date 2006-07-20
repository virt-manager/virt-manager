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

from vncViewer.vnc import GRFBViewer

class vmmConsole(gobject.GObject):
    __gsignals__ = {
        "action-show-details": (gobject.SIGNAL_RUN_FIRST,
                                gobject.TYPE_NONE, (str,str)),
        "action-launch-terminal": (gobject.SIGNAL_RUN_FIRST,
                                   gobject.TYPE_NONE, (str,str)),
        "action-save-domain": (gobject.SIGNAL_RUN_FIRST,
                                 gobject.TYPE_NONE, (str,str))
        }
    def __init__(self, config, vm):
        self.__gobject_init__()
        self.window = gtk.glade.XML(config.get_glade_file(), "vmm-console")
        self.config = config
        self.vm = vm

        topwin = self.window.get_widget("vmm-console")
        topwin.hide()
        topwin.set_title(vm.get_name() + " " + topwin.get_title())

        self.window.get_widget("control-run").set_icon_widget(gtk.Image())
        self.window.get_widget("control-run").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_run.png")

        self.window.get_widget("control-pause").set_icon_widget(gtk.Image())
        self.window.get_widget("control-pause").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_pause.png")

        self.window.get_widget("control-shutdown").set_icon_widget(gtk.Image())
        self.window.get_widget("control-shutdown").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_shutdown.png")

        self.window.get_widget("control-terminal").set_icon_widget(gtk.Image())
        self.window.get_widget("control-terminal").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_launch_term.png")

        self.window.get_widget("control-save").set_icon_widget(gtk.Image())
        self.window.get_widget("control-save").get_icon_widget().set_from_file(config.get_icon_dir() + "/icon_save.png")

        self.vncViewer = GRFBViewer()
        scrolledWin = gtk.ScrolledWindow()

        vp = gtk.Viewport()
        vp.set_shadow_type(gtk.SHADOW_NONE)
        vp.add(self.vncViewer)
        scrolledWin.add(vp)

        self.window.get_widget("console-pages").set_show_tabs(False)
        self.window.get_widget("console-pages").append_page(scrolledWin, gtk.Label("VNC"))

        scrolledWin.show()
        self.vncViewer.show()

        self.ignorePause = False

        self.window.signal_autoconnect({
            "on_vmm_console_delete_event": self.close,

            "on_control_run_clicked": self.control_vm_run,
            "on_control_shutdown_clicked": self.control_vm_shutdown,
            "on_control_pause_toggled": self.control_vm_pause,

            "on_menu_vm_run_activate": self.control_vm_run,
            "on_menu_vm_shutdown_activate": self.control_vm_shutdown,
            "on_menu_vm_pause_activate": self.control_vm_pause,

            "on_control_terminal_clicked": self.control_vm_terminal,
            "on_control_save_clicked": self.control_vm_save_domain,
            "on_control_details_clicked": self.control_vm_details,

            "on_menu_vm_terminal_activate": self.control_vm_terminal,
            "on_menu_vm_save_activate": self.control_vm_save_domain,
            "on_menu_vm_details_activate": self.control_vm_details,

            "on_menu_vm_close_activate": self.close,

            "on_console_auth_login_clicked": self.try_login,
            })

        self.vm.connect("status-changed", self.update_widget_states)
        self.update_widget_states(vm, vm.status())

        self.vncViewer.connect("disconnected", self._vnc_disconnected)

    def show(self):
        dialog = self.window.get_widget("vmm-console")
        dialog.show_all()
        dialog.present()

    def close(self,ignore1=None,ignore2=None):
        self.window.get_widget("vmm-console").hide()
        if self.vncViewer.is_connected():
	    try:
                self.vncViewer.disconnect_from_host()
	    except:
		print "Failure when disconnecting"
        return 1

    def control_vm_run(self, src):
        return 0

    def _vnc_disconnected(self, src):
        self.activate_auth_page()

    def try_login(self, src=None):
        password = self.window.get_widget("console-auth-password").get_text()
        protocol, host, port = self.vm.get_console_info()

        if self.vm.get_id() == 0:
            return

        #print protocol + "://" + host + ":" + str(port)
        if protocol != "vnc":
            self.activate_unavailable_page()
            return

        if not(self.vncViewer.is_connected()):
	    try:
                self.vncViewer.connect_to_host(host, port)
	    except:
		print "Unable to activate console"
                self.activate_unavailable_page()
		return
        if self.vncViewer.is_authenticated():
            self.activate_viewer_page()
        elif password:
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

    def activate_screenshot_page(self):
        self.window.get_widget("console-pages").set_current_page(1)

    def activate_auth_page(self):
        pw = self.config.get_console_password(self.vm)
        self.window.get_widget("console-auth-password").set_text(pw)
        if pw != None and pw != "":
            self.window.get_widget("console-auth-remember").set_active(True)
        else:
            self.window.get_widget("console-auth-remember").set_active(False)
        self.window.get_widget("console-pages").set_current_page(2)

    def activate_viewer_page(self):
        self.window.get_widget("console-pages").set_current_page(3)
                    
    def control_vm_shutdown(self, src):
        status = self.vm.status()
        if not(status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]):
            self.vm.shutdown()
        else:
            print "Shutdown requested, but machine is already shutting down / shutoff"

    def control_vm_pause(self, src):
        if self.ignorePause:
            return

        status = self.vm.status()
        if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
            print "Pause/resume requested, but machine is shutdown / shutoff"
        else:
            if status in [ libvirt.VIR_DOMAIN_PAUSED ]:
                if not src.get_active():
                    self.vm.resume()
                else:
                    print "Pause requested, but machine is already paused"
            else:
                if src.get_active():
                    self.vm.suspend()
                else:
                    print "Resume requested, but machine is already running"

    def control_vm_terminal(self, src):
        self.emit("action-launch-terminal", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_save_domain(self, src):
        self.emit("action-save-domain", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def control_vm_details(self, src):
        self.emit("action-show-details", self.vm.get_connection().get_uri(), self.vm.get_uuid())

    def update_widget_states(self, vm, status):
        self.ignorePause = True
        try:
            if status in [ libvirt.VIR_DOMAIN_SHUTOFF, libvirt.VIR_DOMAIN_CRASHED ]:
                self.window.get_widget("control-run").set_sensitive(True)
                self.window.get_widget("menu-vm-run").set_sensitive(True)
            else:
                self.window.get_widget("control-run").set_sensitive(False)
                self.window.get_widget("menu-vm-run").set_sensitive(False)

            if status in [ libvirt.VIR_DOMAIN_SHUTDOWN, libvirt.VIR_DOMAIN_SHUTOFF ,libvirt.VIR_DOMAIN_CRASHED ] or vm.is_read_only():
                self.window.get_widget("control-pause").set_sensitive(False)
                self.window.get_widget("control-shutdown").set_sensitive(False)
                self.window.get_widget("control-terminal").set_sensitive(False)
                self.window.get_widget("control-save").set_sensitive(False)
                self.window.get_widget("menu-vm-pause").set_sensitive(False)
                self.window.get_widget("menu-vm-shutdown").set_sensitive(False)
                self.window.get_widget("menu-vm-terminal").set_sensitive(False)
                self.window.get_widget("menu-vm-save").set_sensitive(False)
            else:
                self.window.get_widget("control-pause").set_sensitive(True)
                self.window.get_widget("control-shutdown").set_sensitive(True)
                self.window.get_widget("control-terminal").set_sensitive(True)
                self.window.get_widget("control-save").set_sensitive(True)
                self.window.get_widget("menu-vm-pause").set_sensitive(True)
                self.window.get_widget("menu-vm-shutdown").set_sensitive(True)
                self.window.get_widget("menu-vm-terminal").set_sensitive(True)
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

                        # Set 60% gray overlayed
                        cr.set_source_rgba(0, 0, 0, 0.6)
                        cr.rectangle(0, 0, width, height)
                        cr.fill()

                        # Render a big text 'paused' across it
                        cr.set_source_rgba(1, 1,1, 1)
                        cr.set_font_size(80)
                        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_NORMAL)
                        overlay = "paused"
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
                    self.try_login()
        except:
            print "Couldn't open console " + str(sys.exc_info()[0]) + " " + str(sys.exc_info()[1])
            self.ignorePause = False
        self.ignorePause = False

gobject.type_register(vmmConsole)

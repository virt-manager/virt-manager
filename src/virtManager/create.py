#
# Copyright (C) 2006 Red Hat, Inc.
# Copyright (C) 2006 Hugh O. Brock <hbrock@redhat.com>
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
import gtk
import gtk.gdk
import gtk.glade

from rhpl.exception import installExceptionHandler
from rhpl.translate import _, N_, textdomain, utf8

class vmmCreate(gobject.GObject):
    def __init__(self, config):
        self.__gobject_init__()
        self.xml = gtk.glade.XML(config.get_glade_file(), "vmm-create")
        self.window = self.xml.get_widget("vmm-create")
        self.window.hide()
        self.set_initial_state()
        self.config = config
        
    def show(self):
        self.window.show_all()

    def set_initial_state(self):
        # set up graphics and events for the create wizard
        notebook = self.xml.get_widget("create-pages")
        notebook.set_show_tabs(False)

        #XXX I don't think I should have to go through and set a bunch of background colors
        # in code, but apparently I do...
        black = gtk.gdk.color_parse("#000")
        self.xml.get_widget("intro-title").modify_bg(gtk.STATE_NORMAL,black)
        self.xml.get_widget("page1-title").modify_bg(gtk.STATE_NORMAL,black)
        self.xml.get_widget("page2-title").modify_bg(gtk.STATE_NORMAL,black)
        self.xml.get_widget("page3-title").modify_bg(gtk.STATE_NORMAL,black)
        self.xml.get_widget("page3a-title").modify_bg(gtk.STATE_NORMAL,black)
        self.xml.get_widget("page4-title").modify_bg(gtk.STATE_NORMAL,black)
        self.xml.get_widget("page5-title").modify_bg(gtk.STATE_NORMAL,black)
        self.xml.get_widget("page6-title").modify_bg(gtk.STATE_NORMAL,black)

        self.reset_state()

    def reset_state(self):
        notebook = self.xml.get_widget("create-pages")
        notebook.set_current_page(0)

        # add code here to clear any previously set create wizard values and set
        # the buttons to the proper state

    def forward(self):
        notebook = self.xml.get_widget("create-pages")
        notebook.next_page()

    def back(self):
        notebook = self.xml.get_widget("create-pages")
        notebook.prev_page()
        
    def page_changed(self):
        notebook = self.xml.get_widget("create-pages")
        page_number = notebook.get_current_page()
        if(page_number == 0):
            #set up the front page

        elif(page_number == 1):
            #set up the system-name page

    

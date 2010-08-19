# mainmenu.py - Copyright (C) 2009 Red Hat, Inc.
# Written by Darryl L. Pierce <dpierce@redhat.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA  02110-1301, USA.  A copy of the GNU General Public License is
# also available at http://www.gnu.org/copyleft/gpl.html.

from snack import *
import traceback

import utils
import logging

EXIT_MENU = 99

class MenuScreen:
    def __init__(self, title):
        self.__title = title

    def start(self):
        finished = False
        while finished == False:
            screen = SnackScreen()
            menu = Listbox(height = 0, width = 0, returnExit = 1)
            for menu_item in self.get_menu_items():
                menu.append(menu_item[0], menu_item[1])
            menu.append("Exit Menu", EXIT_MENU)
            gridform = GridForm(screen, self.__title, 1, 4)
            gridform.add(menu, 0, 0)
            result = gridform.run();
            screen.popWindow()
            screen.finish()

            try:
                if result.current() == EXIT_MENU: finished = True
                else: self.handle_selection(result.current())
            except Exception, error:
                screen = SnackScreen()
                logging.info("An exception occurred: %s" % str(error))
                ButtonChoiceWindow(screen,
                                   "An Exception Has Occurred",
                                   str(error) + "\n" + traceback.format_exc(),
                                   buttons = ["OK"])
                screen.popWindow()
                screen.finish()
                finished = True

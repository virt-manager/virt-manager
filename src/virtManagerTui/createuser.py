#
# createuser.py - Copyright (C) 2009 Red Hat, Inc.
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

import snack
from newt_syrup.configscreen import ConfigScreen
from userworker import UserWorker

import libuser

DETAILS_PAGE = 1
CONFIRM_PAGE = 2

class CreateUserConfigScreen(ConfigScreen):
    def __init__(self):
        ConfigScreen.__init__(self, "Create A User Account")
        self.__username = None
        self.__password = None
        self.__confirm = None
        self.__adminuser = None
        self.__useradmin = libuser.admin()
        self.__user_worker = UserWorker()

    def get_elements_for_page(self, screen, page):
        if   page is DETAILS_PAGE:
            return self.get_details_page(screen)
        elif page is CONFIRM_PAGE:
            return self.get_confirm_page(screen)

    def validate_input(self, page, errors):
        if page is DETAILS_PAGE:
            if len(self.__username.value()) > 0:
                name = self.__username.value()
                if self.__useradmin.lookupUserByName(name) is None:
                    if len(self.__password.value()) > 0:
                        if self.__password.value() == self.__confirm.value():
                            return True
                        else:
                            errors.append("Passwords do not match.")
                    else:
                        errors.append("You must enter a password.")
                else:
                    errors.append("User %s already exists." % name)
            else:
                errors.append("You must enter a username.")
            self.__confirm.value()
        return False

    def process_input(self, page):
        if page is CONFIRM_PAGE:
            self.__user_worker.create_user(self.__username.value(),
                                           self.__password.value(),
                                           "wheel" if self.__adminuser.value() else None)
            self.set_finished()

    def page_has_next(self, page):
        return (page is DETAILS_PAGE)

    def page_has_back(self, page):
        return (page is CONFIRM_PAGE)

    def page_has_finish(self, page):
        return (page is CONFIRM_PAGE)

    def get_details_page(self, screen):
        ignore = screen

        if self.__username is None:
            self.__username = snack.Entry(50, "")
            self.__password = snack.Entry(50, "", password=1)
            self.__confirm  = snack.Entry(50, "", password=1)
            self.__adminuser = snack.Checkbox("This user is an administrator", False)
        grid = snack.Grid(2, 4)
        grid.setField(snack.Label("Username:"), 0, 0, anchorRight=1)
        grid.setField(self.__username, 1, 0, anchorLeft=1)
        grid.setField(snack.Label("Password:"), 0, 1, anchorRight=1)
        grid.setField(self.__password, 1, 1, anchorLeft=1)
        grid.setField(snack.Label("Confirm password:"), 0, 2, anchorRight=1)
        grid.setField(self.__confirm, 1, 2, anchorLeft=1)
        grid.setField(snack.Label(" "), 0, 3)
        grid.setField(self.__adminuser, 1, 3, anchorLeft=1)
        return [snack.Label("Enter The User Details"),
                grid]

    def get_confirm_page(self, screen):
        ignore = screen
        grid = snack.Grid(1, 2)
        grid.setField(snack.Label("Username: %s" % self.__username.value()), 0, 0)
        admin_label = "is not"
        if self.__adminuser.value():
            admin_label = "is"
        grid.setField(snack.Label("This user %s an administrator." % admin_label), 0, 1)
        return [snack.Label("Create this user account?"),
                grid]

def CreateUser():
    screen = CreateUserConfigScreen()
    screen.start()

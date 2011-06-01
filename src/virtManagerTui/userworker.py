# userworker.py - Copyright (C) 2009 Red Hat, Inc.
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

import libuser

class UserWorker:
    '''Provides APIs for creating, modifying and deleting user accounts.'''
    def __init__(self):
        self.__admin = libuser.admin()

    def create_user(self, username, password, other_group):
        '''Creates a new user account with the provides username,
        password. The user is also added to the optional group
        if one is specified.'''
        user = self.__admin.initUser(username)
        user.set('pw_passwd', password)
        self.__admin.addUser(user)
        if other_group is not None:
            group = self.__admin.lookupGroupByName(other_group)
            if group is None:
                raise Exception("Invalid group specified: %s" % other_group)
            user.add('pw_gid', group.get('pw_gid')[0])
            self.__admin.modifyUser(user)

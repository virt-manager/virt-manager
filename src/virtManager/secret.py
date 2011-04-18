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
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
# MA 02110-1301 USA.
#


class vmmSecret(object):
    def __init__(self, name, secret=None, attributes=None):

        self.name = name
        self.secret = secret
        if attributes == None:
            attributes = {}
        self.attributes = attributes

    def set_secret(self, data):
        self.secret = data

    def get_secret(self):
        return self.secret

    def get_name(self):
        return self.name

    def get_attributes(self):
        return self.attributes

    def has_attribute(self, key):
        return key in self.attributes

    def add_attribute(self, key, value):
        if type(value) != str:
            value = str(value)

        self.attributes[key] = value

    def list_attributes(self):
        return self.attributes.keys()

    def get_attribute(self, key):
        return self.attributes[key]

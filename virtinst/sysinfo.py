#
# Copyright (C) 2016 Red Hat, Inc.
# Copyright (C) 2016 SUSE LINUX Products GmbH, Nuernberg, Germany.
# Charles Arnold <carnold suse com>
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
"""
Classes for building and installing with libvirt <sysinfo> XML
"""

from .xmlbuilder import XMLBuilder, XMLProperty


class SYSInfo(XMLBuilder):
    """
    Top level class for <sysinfo type='smbios'> object XML
    """

    _XML_ROOT_NAME = "sysinfo"
    _XML_PROP_ORDER = ["type",
        "bios_vendor", "bios_version", "bios_date", "bios_release",
        "system_manufacturer", "system_product", "system_version",
        "system_serial", "system_uuid", "system_sku", "system_family",
        "baseBoard_manufacturer", "baseBoard_product", "baseBoard_version",
        "baseBoard_serial", "baseBoard_asset", "baseBoard_location"]

    type = XMLProperty("./@type")

    bios_vendor = XMLProperty("./bios/entry[@name='vendor']")
    bios_version = XMLProperty("./bios/entry[@name='version']")
    bios_date = XMLProperty("./bios/entry[@name='date']")
    bios_release = XMLProperty("./bios/entry[@name='release']")

    system_manufacturer = XMLProperty("./system/entry[@name='manufacturer']")
    system_product = XMLProperty("./system/entry[@name='product']")
    system_version = XMLProperty("./system/entry[@name='version']")
    system_serial = XMLProperty("./system/entry[@name='serial']")
    system_uuid = XMLProperty("./system/entry[@name='uuid']")
    system_sku = XMLProperty("./system/entry[@name='sku']")
    system_family = XMLProperty("./system/entry[@name='family']")

    baseBoard_manufacturer = XMLProperty(
        "./baseBoard/entry[@name='manufacturer']")
    baseBoard_product = XMLProperty("./baseBoard/entry[@name='product']")
    baseBoard_version = XMLProperty("./baseBoard/entry[@name='version']")
    baseBoard_serial = XMLProperty("./baseBoard/entry[@name='serial']")
    baseBoard_asset = XMLProperty("./baseBoard/entry[@name='asset']")
    baseBoard_location = XMLProperty("./baseBoard/entry[@name='location']")

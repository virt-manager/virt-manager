# Copyright (C) 2016 Red Hat, Inc.
# Copyright (C) 2016 SUSE LINUX Products GmbH, Nuernberg, Germany.
# Charles Arnold <carnold suse com>
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from ..xmlbuilder import XMLBuilder, XMLChildProperty, XMLProperty


class _SysinfoEntry(XMLBuilder):
    XML_NAME = "entry"
    name = XMLProperty("./@name")
    value = XMLProperty(".")
    file = XMLProperty("./@file")


class _SysinfoOemString(_SysinfoEntry):
    pass


class DomainSysinfo(XMLBuilder):
    """
    Class for building and domain <sysinfo> XML
    """

    XML_NAME = "sysinfo"
    _XML_PROP_ORDER = ["type",
        "bios_vendor", "bios_version", "bios_date", "bios_release",
        "system_manufacturer", "system_product", "system_version",
        "system_serial", "system_uuid", "system_sku", "system_family",
        "baseBoard_manufacturer", "baseBoard_product", "baseBoard_version",
        "baseBoard_serial", "baseBoard_asset", "baseBoard_location",
        "chassis_manufacturer", "chassis_version",
        "chassis_serial", "chassis_asset", "chassis_sku", "oemStrings"]

    type = XMLProperty("./@type")

    bios_date = XMLProperty("./bios/entry[@name='date']")
    bios_vendor = XMLProperty("./bios/entry[@name='vendor']")
    bios_version = XMLProperty("./bios/entry[@name='version']")
    bios_release = XMLProperty("./bios/entry[@name='release']")

    system_uuid = XMLProperty("./system/entry[@name='uuid']")
    system_manufacturer = XMLProperty("./system/entry[@name='manufacturer']")
    system_product = XMLProperty("./system/entry[@name='product']")
    system_version = XMLProperty("./system/entry[@name='version']")
    system_serial = XMLProperty("./system/entry[@name='serial']")
    system_sku = XMLProperty("./system/entry[@name='sku']")
    system_family = XMLProperty("./system/entry[@name='family']")

    baseBoard_manufacturer = XMLProperty(
        "./baseBoard/entry[@name='manufacturer']")
    baseBoard_product = XMLProperty("./baseBoard/entry[@name='product']")
    baseBoard_version = XMLProperty("./baseBoard/entry[@name='version']")
    baseBoard_serial = XMLProperty("./baseBoard/entry[@name='serial']")
    baseBoard_asset = XMLProperty("./baseBoard/entry[@name='asset']")
    baseBoard_location = XMLProperty("./baseBoard/entry[@name='location']")

    chassis_manufacturer = XMLProperty("./chassis/entry[@name='manufacturer']")
    chassis_version = XMLProperty("./chassis/entry[@name='version']")
    chassis_serial = XMLProperty("./chassis/entry[@name='serial']")
    chassis_asset = XMLProperty("./chassis/entry[@name='asset']")
    chassis_sku = XMLProperty("./chassis/entry[@name='sku']")

    oemStrings = XMLChildProperty(
            _SysinfoOemString, relative_xpath="./oemStrings")
    entries = XMLChildProperty(_SysinfoEntry)

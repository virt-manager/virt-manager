# Copyright (C) 2013 Red Hat, Inc.
#
# Copyright 2012
# Eiichi Tsukata <devel@etsukata.com>
#
# This work is licensed under the GNU GPLv2.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceMemballoon(Device):
    _XML_ROOT_NAME = "memballoon"

    MODEL_DEFAULT = "default"
    MODELS = ["virtio", "xen", "none"]

    model = XMLProperty("./@model",
                        default_name=MODEL_DEFAULT,
                        default_cb=lambda s: "virtio")

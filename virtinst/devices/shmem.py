#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

from .device import Device
from ..xmlbuilder import XMLProperty


class DeviceShMem(Device):
    XML_NAME = "shmem"
    _XML_PROP_ORDER = [
        "name", "role",
        "type", "size", "size_unit",
        "server_path", "msi_vectors", "msi_ioeventfd",
    ]

    MODEL_IVSHMEM = "ivshmem"
    MODEL_IVSHMEM_PLAIN = "ivshmem-plain"
    MODEL_IVSHMEM_DOORBELL = "ivshmem-doorbell"
    MODELS = [MODEL_IVSHMEM, MODEL_IVSHMEM_PLAIN, MODEL_IVSHMEM_DOORBELL]

    ROLE_MASTER = "master"
    ROLE_PEER = "peer"
    ROLES = [ROLE_MASTER, ROLE_PEER]

    name = XMLProperty("./@name")
    role = XMLProperty("./@role")

    type = XMLProperty("./model/@type")

    size = XMLProperty("./size", is_int=True)
    size_unit = XMLProperty("./size/@unit")

    server_path = XMLProperty("./server/@path")
    msi_vectors = XMLProperty("./msi/@vectors", is_int=True)
    msi_ioeventfd = XMLProperty("./msi/@ioeventfd", is_onoff=True)

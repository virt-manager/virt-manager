# Copyright (C) 2025 Red Hat, Inc.
#
# This work is licensed under the GNU GPLv2 or later.
# See the COPYING file in the top-level directory.

"""
OVF descriptor parser used when importing OVA files.

An OVA is a tar archive containing an OVF descriptor (.ovf) and one or
more VMDK disk images.  The functions here extract the descriptor and
parse it into an :class:`_OVFInfo` instance that the New-VM wizard uses
to pre-populate name, memory, CPU and disk fields.
"""

import os
import tarfile
import xml.etree.ElementTree as ET


# ---------------------------------------------------------------------------
# OVF namespace helpers
# ---------------------------------------------------------------------------

_OVF_NS = "http://schemas.dmtf.org/ovf/envelope/1"
_RASD_NS = (
    "http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/"
    "CIM_ResourceAllocationSettingData"
)

# RASD ResourceType values we care about (DMTF DSP0004)
_RT_CPU      = 3
_RT_MEM      = 4
_RT_ETHERNET = 10
_RT_DISK      = 17   # hard disk drive reference in RASD Items
_RT_DISK2     = 31   # alternative used by some exporters
_RT_DISK3     = 32   # alternative used by some exporters
# Disk controller ResourceType values (DMTF DSP0004, with de-facto extensions)
_RT_IDE_CTRL  =  5   # IDE Controller
_RT_SCSI_CTRL =  6   # Parallel SCSI HBA / SAS
_RT_SATA_CTRL = 20   # SATA Controller (DMTF says USB, but VMware & VirtualBox use this for SATA)


def _ovf(tag):
    """Return a Clark-notation OVF tag, e.g. '{…ovf/envelope/1}Disk'."""
    return "{%s}%s" % (_OVF_NS, tag)


def _rasd(tag):
    """Return a Clark-notation RASD tag."""
    return "{%s}%s" % (_RASD_NS, tag)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

class _OVFInfo:
    """Container for data extracted from an OVF descriptor."""

    def __init__(self):
        self.name = "imported-vm"
        self.vcpus = 1
        self.memory_mb = 512
        # List of dicts: {"vmdk": relative-name-in-ova, "size_gb": float,
        #                  "bus": str-or-None}  bus is "ide", "scsi", or "sata"
        # (or None when the controller type could not be determined).
        self.disks = []
        self.net_count = 0
        # Disk bus type inferred from the OVF controller ("ide", "scsi", "sata").
        # Defaults to "sata" — the safest choice: works on Windows and Linux
        # without extra drivers, unlike "virtio" which requires a paravirtual
        # block driver that most non-Linux guests do not ship with.
        self.disk_bus = "sata"
        # Raw OS type strings extracted from OperatingSystemSection.
        # Resolution to a libosinfo OS object is done by the caller via
        # virtinst.OSDB.guess_os_from_ovf_hint().
        self.ovf_vmw_type = None   # VMware vmw:osType attribute
        self.ovf_vbox_type = None  # VirtualBox <vbox:OSType> element text
        self.ovf_cim_id = None     # DMTF CIM OS integer from ovf:id

    def __repr__(self):  # pragma: no cover
        return (
            "<_OVFInfo name=%r vcpus=%d mem_mb=%d disks=%r nets=%d>"
            % (self.name, self.vcpus, self.memory_mb, self.disks, self.net_count)
        )


# Vendor-specific namespace URIs used in OperatingSystemSection attributes.
_VMW_NS  = "http://www.vmware.com/schema/ovf"
_VBOX_NS = "http://www.virtualbox.org/ovf/machine"

# Mapping tables have moved to virtinst/osdict.py — see OSDB.guess_os_from_ovf_hint().


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _parse_ovf(ovf_content):
    """
    Parse OVF XML *bytes* or *str* and return a :class:`_OVFInfo`.

    Raises :exc:`RuntimeError` if required sections are missing.
    """
    if isinstance(ovf_content, (bytes, bytearray)):
        root = ET.fromstring(ovf_content)
    else:
        root = ET.fromstring(ovf_content.encode())

    info = _OVFInfo()

    # --- VirtualSystem ---------------------------------------------------
    vs = root.find(_ovf("VirtualSystem"))
    if vs is None:
        raise RuntimeError(
            "No VirtualSystem element found in OVF descriptor."
        )

    name_el = vs.find(_ovf("Name"))
    if name_el is not None and name_el.text:
        info.name = name_el.text.strip()
    else:
        vsid = vs.get(_ovf("id")) or vs.get("id")
        if vsid:
            info.name = vsid

    # --- OperatingSystemSection: extract raw vendor OS identifiers ---------
    # Resolution to a libosinfo OS is done by the caller via
    # virtinst.OSDB.guess_os_from_ovf_hint().
    os_section = vs.find(_ovf("OperatingSystemSection"))
    if os_section is None:
        os_section = root.find(_ovf("OperatingSystemSection"))
    if os_section is not None:
        info.ovf_vmw_type = os_section.get("{%s}osType" % _VMW_NS) or None
        vbox_el = os_section.find("{%s}OSType" % _VBOX_NS)
        if vbox_el is not None and vbox_el.text:
            info.ovf_vbox_type = vbox_el.text.strip() or None
        info.ovf_cim_id = (
            os_section.get("{%s}id" % _OVF_NS) or os_section.get("id") or None
        )

    # --- References: file id → vmdk filename ----------------------------
    file_map = {}  # id → href
    for ref in root.findall(_ovf("References") + "/" + _ovf("File")):
        fid  = ref.get(_ovf("id"))  or ref.get("id")
        href = ref.get(_ovf("href")) or ref.get("href")
        if fid and href:
            file_map[fid] = href

    # --- DiskSection: disk id → file ref & capacity ---------------------
    disk_file_map = {}   # diskId → fileRef
    disk_cap_map  = {}   # diskId → capacity in bytes

    disk_section = root.find(_ovf("DiskSection"))
    if disk_section is not None:
        for disk_el in disk_section.findall(_ovf("Disk")):
            did  = disk_el.get(_ovf("diskId")) or disk_el.get("diskId")
            fref = disk_el.get(_ovf("fileRef")) or disk_el.get("fileRef")
            cap  = (disk_el.get(_ovf("capacity"))
                    or disk_el.get("capacity") or "0")
            alloc_units = (
                disk_el.get(_ovf("capacityAllocationUnits"))
                or disk_el.get("capacityAllocationUnits")
                or "byte * 2^30"
            )
            if not did:
                continue
            disk_file_map[did] = fref
            try:
                cap_val = int(cap)
                if "2^30" in alloc_units:
                    cap_bytes = cap_val * (2 ** 30)
                elif "2^20" in alloc_units:
                    cap_bytes = cap_val * (2 ** 20)
                else:
                    cap_bytes = cap_val   # assume bytes
            except (ValueError, TypeError):
                cap_bytes = 0
            disk_cap_map[did] = cap_bytes

    # --- VirtualHardwareSection -----------------------------------------
    vhs = vs.find(_ovf("VirtualHardwareSection"))
    if vhs is None:
        raise RuntimeError(
            "No VirtualHardwareSection element found in OVF descriptor."
        )

    # First pass: map controller InstanceID → bus type string.
    # We need this before the disk loop because disk items reference their
    # controller via a Parent element that points to the controller's InstanceID.
    ctrl_bus = {}   # int instanceId → "ide" | "scsi" | "sata"
    for item in vhs.findall(_ovf("Item")):
        rtype_el = item.find(_rasd("ResourceType"))
        if rtype_el is None or not rtype_el.text:
            continue
        try:
            rtype = int(rtype_el.text.strip())
        except (ValueError, TypeError):
            continue
        if rtype not in (_RT_IDE_CTRL, _RT_SCSI_CTRL, _RT_SATA_CTRL):
            continue
        iid_el = item.find(_rasd("InstanceID")) or item.find(_rasd("InstanceId"))
        if iid_el is None or not iid_el.text:
            continue
        try:
            iid = int(iid_el.text.strip())
        except (ValueError, TypeError):
            continue
        if rtype == _RT_IDE_CTRL:
            ctrl_bus[iid] = "ide"
        elif rtype == _RT_SCSI_CTRL:
            ctrl_bus[iid] = "scsi"
        elif rtype == _RT_SATA_CTRL:
            ctrl_bus[iid] = "sata"

    # Collect disk RASD items with their controller slot info for ordering
    disk_items = []   # (parent_key, addr_key, disk_id)

    for item in vhs.findall(_ovf("Item")):
        rtype_el = item.find(_rasd("ResourceType"))
        if rtype_el is None:
            continue
        try:
            rtype = int(rtype_el.text.strip())
        except (ValueError, TypeError):
            continue

        if rtype == _RT_CPU:
            qty_el = item.find(_rasd("VirtualQuantity"))
            if qty_el is not None and qty_el.text:
                try:
                    info.vcpus = max(1, int(qty_el.text.strip()))
                except ValueError:
                    pass

        elif rtype == _RT_MEM:
            qty_el   = item.find(_rasd("VirtualQuantity"))
            units_el = item.find(_rasd("AllocationUnits"))
            if qty_el is not None and qty_el.text:
                try:
                    qty = int(qty_el.text.strip())
                    units = (
                        units_el.text.strip()
                        if units_el is not None
                        else "MegaBytes"
                    )
                    if any(k in units for k in ("MegaBytes", "MB", "2^20")):
                        info.memory_mb = qty
                    elif any(k in units for k in ("GigaBytes", "GB", "2^30")):
                        info.memory_mb = qty * 1024
                    elif any(k in units for k in ("KiloBytes", "KB", "2^10")):
                        info.memory_mb = qty // 1024
                    else:
                        info.memory_mb = qty
                    info.memory_mb = max(64, info.memory_mb)
                except ValueError:
                    pass

        elif rtype == _RT_ETHERNET:
            info.net_count += 1

        elif rtype in (_RT_DISK, _RT_DISK2, _RT_DISK3):
            res_el = item.find(_rasd("HostResource"))
            if res_el is not None and res_el.text:
                href = res_el.text.strip()
                # Typical value: "ovf:/disk/disk1"
                if "/disk/" in href:
                    disk_id = href.split("/disk/")[-1]
                    # Capture controller slot info for correct ordering
                    parent_el = item.find(_rasd("Parent"))
                    addr_el   = item.find(_rasd("AddressOnParent"))
                    try:
                        parent_key = int(parent_el.text.strip()) if parent_el is not None else 0
                    except (ValueError, TypeError):
                        parent_key = 0
                    try:
                        addr_key = int(addr_el.text.strip()) if addr_el is not None else 0
                    except (ValueError, TypeError):
                        addr_key = 0
                    disk_items.append((parent_key, addr_key, disk_id))

    # Sort by (controller, slot) so multi-disk VMs attach in the right order
    disk_items.sort(key=lambda t: (t[0], t[1]))

    for ctrl_iid, _slot, disk_id in disk_items:
        file_ref  = disk_file_map.get(disk_id)
        vmdk_name = file_map.get(file_ref) if file_ref else None
        cap_bytes = disk_cap_map.get(disk_id, 0)
        # Resolve the bus type from the controller this disk is attached to.
        # ctrl_iid is the controller's InstanceID from the disk item's
        # rasd:Parent element; ctrl_bus maps it to "ide", "scsi", or "sata".
        disk_bus = ctrl_bus.get(ctrl_iid)
        if vmdk_name:
            info.disks.append({
                "vmdk": vmdk_name,
                "size_gb": cap_bytes / (1024 ** 3) if cap_bytes else 0.0,
                "bus": disk_bus,
            })

    # Derive the overall disk_bus from the first (boot) disk's controller.
    # This is used in createvm.py as the bus type for all disk devices.
    boot_bus = next((d["bus"] for d in info.disks if d.get("bus")), None)
    if boot_bus:
        info.disk_bus = boot_bus

    # Fallback: some OVAs omit RASD disk items; use all referenced VMDKs.
    # bus=None here; createvm.py will fall back to ovf_info.disk_bus ("sata").
    if not info.disks:
        for unused_fid, href in file_map.items():
            if href.lower().endswith(".vmdk"):
                info.disks.append({"vmdk": href, "size_gb": 0.0, "bus": None})

    return info


def _read_ovf_from_ova(ova_path):
    """
    Open *ova_path* as a tar archive and return the raw bytes of the first
    ``.ovf`` member without extracting anything to disk.

    Raises :exc:`RuntimeError` if no ``.ovf`` member is found.
    """
    with tarfile.open(ova_path, "r:*") as tar:
        ovf_members = [
            m for m in tar.getmembers()
            if os.path.basename(m.name).lower().endswith(".ovf")
        ]
        if not ovf_members:
            raise RuntimeError(
                "No .ovf descriptor found inside the OVA archive."
            )
        f = tar.extractfile(ovf_members[0])
        return f.read()

==========
virt-clone
==========

-------------------------------------
clone existing virtual machine images
-------------------------------------

:Manual section: 1
:Manual group: Virtualization Support


SYNOPSIS
========


``virt-clone`` [OPTION]...


DESCRIPTION
===========


``virt-clone`` is a command line tool for cloning existing virtual machine
images using the ``libvirt`` hypervisor management library. It will copy
the disk images of any existing virtual machine, and define a new guest
with an identical virtual hardware configuration. Elements which require
uniqueness will be updated to avoid a clash between old and new guests.

By default, virt-clone will show an error if the necessary information to
clone the guest is not provided. The --auto-clone option will generate
all needed input, aside from the source guest to clone.

Please note, virt-clone does not change anything _inside_ the guest OS, it
only duplicates disks and does host side changes. So things like changing
passwords, changing static IP address, etc are outside the scope of this
tool. For these types of changes, please see ``virt-sysprep``.


GENERAL OPTIONS
===============

Most options are not required. Minimum requirements are --original or
--original-xml (to specify the guest to clone), --name, and appropriate
storage options via -file.


``--connect`` URI
    Connect to a non-default hypervisor. See virt-install(1) for details


``-o``, ``--original`` ORIGINAL_GUEST
    Name of the original guest to be cloned. This guest must be shut off.


``--original-xml`` ORIGINAL_XML
    Libvirt guest xml file to use as the original guest. The guest does not need to
    be defined on the libvirt connection. This takes the place of the
    ``--original`` parameter.


``--auto-clone``
    Generate a new guest name, and paths for new storage.

    An example of possible generated output:

    .. code-block::

        Original name        : MyVM
        Generated clone name : MyVM-clone

        Original disk path   : /home/user/foobar.img
        Generated disk path  : /home/user/foobar-clone.img


    If generated names collide with existing VMs or storage, a number is appended,
    such as foobar-clone-1.img, or MyVM-clone-3.


``-n``, ``--name`` NAME
    Name of the new guest virtual machine instance. This must be unique amongst
    all guests known to the hypervisor connection, including those not
    currently active.


``-u``, ``--uuid`` UUID
    UUID for the guest; if none is given a random UUID will be generated. If you
    specify UUID, you should use a 32-digit hexadecimal number. UUID are intended
    to be unique across the entire data center, and indeed world. Bear this in
    mind if manually specifying a UUID


``-f``, ``--file`` PATH
    Path to the file, disk partition, or logical volume to use as the backing store
    for the new guest's virtual disk. If the original guest has multiple disks,
    this parameter must be repeated multiple times, once per disk in the original
    virtual machine.


``--nvram`` NVRAMFILE
    Optional path to the new nvram VARS file, if no path is specified and the
    guest has nvram the new nvram path will be auto-generated. If the guest
    doesn't have nvram this option will be ignored.

``--force-copy`` TARGET
    Force cloning the passed disk target ('hdc', 'sda', etc.). By default,
    ``virt-clone`` will skip certain disks, such as those marked 'readonly' or
    'shareable'.


``--skip-copy`` TARGET
    Skip cloning the passed disk target ('hdc', 'sda', etc.). By default,
    ``virt-clone`` will clone certain disk images, typically read/write
    devices. Use this to skip copying of a specific device, so the new
    VM uses the same storage path as the original VM.


``--nonsparse``
    Fully allocate the new storage if the path being cloned is a sparse file.
    See virt-install(1) for more details on sparse vs. nonsparse.


``--preserve-data``
    No storage is cloned: disk images specified by --file are preserved as is,
    and referenced in the new clone XML. This is useful if you want to clone
    a VM XML template, but not the storage contents.


``--reflink``
    Perform a lightweight copy. This is much faster if source images and destination
    images are all on the same btrfs filesystem. This only works for raw format disk
    images, any non-raw images will not attempt to use refink


``-m``, ``--mac`` MAC
    Fixed MAC address for the guest; If this parameter is omitted, or the value
    ``RANDOM`` is specified a suitable address will be randomly generated. Addresses
    are applied sequentially to the networks as they are listed in the original
    guest XML.


``--print-xml``
    Print the generated clone XML and exit without cloning.


``--replace``
    Before cloning, try a simple ``virsh destroy`` and ``virsh undefine`` on
    any existing VM with the passed ``--name``. If those operations fail (like
    when ``virsh undefine`` requires ``--nvram`` flag), the clone will fail
    and you will need to manually remove the existing VM.


``-h``, ``--help``
    Show the help message and exit


``--version``
    Show program's version number and exit


``--check``
    Enable or disable some validation checks. See virt-install(1) for more details.


``-q``, ``--quiet``
    Suppress non-error output.


``-d``, ``--debug``
    Print debugging information to the terminal when running the install process.
    The debugging information is also stored in
    ``~/.cache/virt-manager/virt-clone.log`` even if this parameter is omitted.


EXAMPLES
========

Clone the guest called ``demo`` on the default connection, auto generating
a new name and disk clone path.

.. code-block::

   # virt-clone \
        --original demo \
        --auto-clone


Clone the guest called ``demo`` which has a single disk to copy

.. code-block::

   # virt-clone \
        --original demo \
        --name newdemo \
        --file /var/lib/xen/images/newdemo.img


Clone a QEMU guest with multiple disks

.. code-block::

   # virt-clone \
        --connect qemu:///system \
        --original demo \
        --name newdemo \
        --file /var/lib/xen/images/newdemo.img \
        --file /var/lib/xen/images/newdata.img


Clone a guest to a physical device which is at least as big as the
original guests disks. If the destination device is bigger, the
new guest can do a filesystem resize when it boots.

.. code-block::

   # virt-clone \
        --connect qemu:///system \
        --original demo \
        --name newdemo \
        --file /dev/HostVG/DemoVM \
        --mac 52:54:00:34:11:54


BUGS
====

Please see https://virt-manager.org/bugs


COPYRIGHT
=========

Copyright (C) Fujitsu Limited, Copyright (C) Red Hat, Inc,
and various contributors.
This is free software. You may redistribute copies of it under the terms
of the GNU General Public License https://www.gnu.org/licenses/gpl.html.
There is NO WARRANTY, to the extent permitted by law.


SEE ALSO
========

``virt-sysprep(1)``, ``virsh(1)``, ``virt-install(1)``, ``virt-manager(1)``, the project website https://virt-manager.org

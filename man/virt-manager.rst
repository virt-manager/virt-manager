============
virt-manager
============

---------------------------------------
Graphical tool for managing libvirt VMs
---------------------------------------

:Manual section: 1
:Manual group: Virtualization Support


SYNOPSIS
========

``virt-manager`` [OPTIONS]


DESCRIPTION
===========


``virt-manager`` is a desktop tool for managing virtual machines. It
provides the ability to control the lifecycle of existing machines
(bootup/shutdown,pause/resume,suspend/restore), provision new virtual
machines and various types of store, manage virtual networks,
access the graphical console of virtual machines, and view performance
statistics, all done locally or remotely.


OPTIONS
=======

Standard GTK options like ``--g-fatal-warnings`` are accepted.

The following options are accepted when running ``virt-manager``


``-h``, ``--help``
    Display command line help summary


``--version``
    Show virt-manager's version number and exit


``-c``, ``--connect``
    Specify the hypervisor connection **URI**


``--debug``
    List debugging output to the console (normally this is only logged in
    ~/.cache/virt-manager/virt-manager.log). This function implies --no-fork.


``--no-fork``
    Don't fork ``virt-manager`` off into the background: run it blocking the
    current terminal. Useful for seeing possible errors dumped to stdout/stderr.


DIALOG WINDOW OPTIONS
=====================

For these options, only the requested window will be shown, the manager
window will not be run in this case. Connection autostart will also
be disabled. All these options require specifying a manual ``--connect``
URI.

``--show-domain-creator``
    Display the wizard for creating new virtual machines


``--show-domain-editor`` NAME|ID|UUID
    Display the dialog for editing properties of the virtual machine with
    unique ID matching either the domain name, ID, or UUID


``--show-domain-performance`` NAME|ID|UUID
    Display the dialog for monitoring performance of the virtual machine with
    unique ID matching either the domain name, ID, or UUID


``--show-domain-console`` NAME|ID|UUID
    Display the virtual console of the virtual machine with
    unique ID matching either the domain name, ID, or UUID


``--show-host-summary``
    Display the host/connection details window.


BUGS
====

Please see https://virt-manager.org/bugs/


COPYRIGHT
=========

Copyright (C) Red Hat, Inc, and various contributors.
This is free software. You may redistribute copies of it under the terms of the GNU General
Public License https://www.gnu.org/licenses/gpl.html. There is NO WARRANTY, to the extent
permitted by law.


SEE ALSO
========

``virsh(1)``, ``virt-viewer(1)``, the project website https://virt-manager.org

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
    Don't fork ``virt-manager`` off into the background.
    See ``VIRT-MANAGER, SSH, AND FORKING`` section for more info.


``--fork``
    Force forking ``virt-manager`` off into the background.
    This is the default behavior.
    See ``VIRT-MANAGER, SSH, AND FORKING`` section for more info.


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


SYSTEM TRAY OPTION
==================

Connection autostart will not be disabled and thus don't require specifying a
manual ``--connect`` URI. But it supports ``--connect`` URI as well:

``--show-systray``
    Launch virt-manager only in system tray


VIRT-MANAGER, SSH, AND FORKING
==============================

Historically, on startup virt-manager would detach from the running
terminal and fork into the background. This was to force any usage of
ssh to call ssh-askpass when it needed a password, rather than silently
asking on a terminal the user probably isn't watching.

openssh 8.4p1 released in Sep 2020 added the SSH_ASKPASS_REQUIRE
environment variable that saves us from having to do the fork dance.
https://man.openbsd.org/ssh.1#SSH_ASKPASS_REQUIRE

virt-manager now sets SSH_ASKPASS_REQUIRE=force.
However to get this to work with libvirt ssh connections, you'll need
libvirt 10.8.0 released in October 1st 2024.

virt-manager no longer forks by defaults.

You can get the old forking behavior with the ``--fork`` option,
or by setting the ``VIRT_MANAGER_DEFAULT_FORK=yes`` environment variable.

However if you find you need forking for a usecase other than temporarily
working around libvirt version issues, please let the virt-manager developers
know by filing a bug report.


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

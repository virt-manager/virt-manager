# Virtual Machine Manager

This application provides a graphical tool for managing virtual machines
via the [libvirt](https://libvirt.org) library.

The front end of the application uses the GTK / Glade libraries for
all user interaction components. The back end uses libvirt for managing
Qemu/KVM and Xen virtual machines, as well as LXC containers. The UI is
primarily tested with KVM, but is intended to be reasonably portable to any
virtualization backend libvirt supports.

For dependency info and installation instructions, see the
[INSTALL.md](INSTALL.md) file.

## Contact

 - All comments / suggestions / patches should be directed to the
   [virt-tools-list](http://www.redhat.com/mailman/listinfo/virt-tools-list)
   mailing list.
 - For IRC we use #virt on OFTC.
 - For bug reporting info, see
   [BugReporting](http://virt-manager.org/page/BugReporting).
 - There are further project details on the
   [virt-manager](http://virt-manager.org/) website.
 - See the [HACKING.md](HACKING.md) file for info about submitting patches or
   contributing translations.

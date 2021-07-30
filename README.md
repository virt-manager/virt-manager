# Virtual Machine Manager

`virt-manager` is a graphical tool for managing virtual machines
via [libvirt](https://libvirt.org). Most usage is with QEMU/KVM
virtual machines, but Xen and libvirt LXC containers are well
supported. Common operations for any libvirt driver should work.

Several command line tools are also provided:

 - `virt-install`: Create new libvirt virtual machines
 - `virt-clone`: Duplicate existing libvirt virtual machines
 - `virt-xml`: Edit existing libvirt virtual machines/manipulate libvirt XML

For dependency info and installation instructions, see the
[INSTALL.md](INSTALL.md) file. If you just want to quickly test the
code from a git checkout, you can launch any of the commands like:

```sh
./virt-manager --debug ...
```

## Contact

 - Discussions and big patch series should go to the
   [virt-tools-list](https://www.redhat.com/mailman/listinfo/virt-tools-list)
   mailing list.
 - For IRC we use #virt on OFTC.
 - For bug reporting info, see
   [virt-manager bug reporting](https://virt-manager.org/bugs).
 - There are further project details on the
   [virt-manager](https://virt-manager.org/) website.
 - See the [CONTRIBUTING.md](CONTRIBUTING.md) file for info about submitting patches or
   contributing translations.

# Basic Install

For starters, if you just want to run `virt-manager/virt-install` to test out
changes, it can be done from the source directory:
```sh
./virt-manager
```

For more details on that, see [CONTRIBUTING.md](CONTRIBUTING.md)


To install the software into `/usr/local` (usually), you can do:
```sh
meson setup build
meson install -C build
```


## Pre-requisite software

A detailed dependency list can be found in [virt-manager.spec.in](virt-manager.spec.in) file.

Minimum version requirements of major components:

   - gettext >= 0.19.6
   - python >= 3.4
   - gtk3 >= 3.22
   - libvirt-python >= 0.6.0
   - pygobject3 >= 3.31.3
   - libosinfo >= 0.2.10
   - gtksourceview >= 3

### Debian/Ubuntu

```
sudo apt install gir1.2-gtk-3.0 gir1.2-gtk-vnc-2.0 gir1.2-gtksource-4 gir1.2-spiceclientgtk-3.0 gir1.2-libosinfo-1.0 gir1.2-libvirt-glib-1.0 gir1.2-vte-2.91 python3-gi python3-gi-cairo python3-libvirt virtinst dconf-gsettings-backend gsettings-backend python3 qemu-user-static libvirt-daemon-system qemu-system qemu-user
```

> [!NOTE]
> Right after installing all dependencies, ensure the `libvirtd` daemon is running; if not, you need to reboot your system

## Optional software

`virt-manager` can optionally use [libguestfs](http://libguestfs.org/)
for inspecting the guests.  For this, `python-libguestfs` >= 1.22 is needed.

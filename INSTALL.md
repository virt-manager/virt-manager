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

On Debian or Ubuntu based distributions, you need to install the
`gobject-introspection` bindings for some dependencies like `libvirt-glib`
and `libosinfo`. Look for package names that start with `'gir'`, for example
`gir1.2-libosinfo-1.0`.


## Optional software

`virt-manager` can optionally use [libguestfs](http://libguestfs.org/)
for inspecting the guests.  For this, `python-libguestfs` >= 1.22 is needed.

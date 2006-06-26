AC_INIT(gnome-virt-manager.spec.in)
AM_INIT_AUTOMAKE(gnome-virt-manager, 0.1.1)

AC_PROG_CC
AC_PROG_LIBTOOL

AC_PYTHON_DEVEL([>= '2.3.4'])

PKG_CHECK_MODULES(PYGTK2, pygtk-2.0 >= 1.99.11)
PKG_CHECK_MODULES(GTK2, gtk+-2.0 >= 2.2.0)

AC_OUTPUT(Makefile
          src/Makefile
          src/virtManager/Makefile
          src/vncViewer/Makefile
          src/graphWidgets/Makefile
          pixmaps/Makefile
          gnome-virt-manager.spec)

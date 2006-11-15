AC_INIT(virt-manager.spec.in)
AM_INIT_AUTOMAKE(virt-manager, 0.2.6)

AC_PROG_CC
AC_PROG_LIBTOOL

AC_PYTHON_DEVEL([>= '2.3.4'])

PKG_CHECK_MODULES(PYGTK2, pygtk-2.0 >= 1.99.11)
PKG_CHECK_MODULES(GTK2, gtk+-2.0 >= 2.2.0)

AC_OUTPUT(Makefile
          pixmaps/Makefile
          po/Makefile
          src/Makefile
          src/virtManager/Makefile
          src/vncViewer/Makefile
          src/graphWidgets/Makefile
          virt-manager.spec)

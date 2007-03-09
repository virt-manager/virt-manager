AC_INIT(virt-manager.spec.in)
AM_INIT_AUTOMAKE(virt-manager, 0.3.1)

AC_PROG_CC
AC_PROG_LIBTOOL

AC_PYTHON_DEVEL([>= '2.3.4'])

PKG_CHECK_MODULES(PYGTK2, pygtk-2.0 >= 1.99.11)
PKG_CHECK_MODULES(GTK2, gtk+-2.0 >= 2.2.0)

dnl ====================================
dnl = Begin tests for scrollkeeper
dnl ====================================
AC_PATH_PROG(SCROLLKEEPER_CONFIG, scrollkeeper-config,no)
if test x$SCROLLKEEPER_CONFIG = xno; then
  AC_MSG_ERROR(Couldn't find scrollkeeper-config. Please install the scrollkeeper package: http://scrollkeeper.sourceforge.net)
fi
dnl ====================================
dnl = End tests for scrollkeeper
dnl ====================================

AC_OUTPUT(Makefile
          pixmaps/Makefile
          po/Makefile
          src/Makefile
          src/virtManager/Makefile
          src/vncViewer/Makefile
          src/graphWidgets/Makefile
          virt-manager.spec
	  help/Makefile
	  help/virt-manager/Makefile
	  help/virt-manager/C/Makefile)

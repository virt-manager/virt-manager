AC_INIT(virt-manager.spec.in)
AM_INIT_AUTOMAKE(virt-manager, 0.4.0)

ALL_LINGUAS="bg bn_IN bs ca cs da de es fi fr gu hi hr hu is it ja kn ko ml mr ms nb nl or pa pl pt_BR pt ro ru sr@Latn sr sv ta te tr uk zh_CN zh_TW"
IT_PROG_INTLTOOL([0.35.0], [no-xml])
AM_GNU_GETTEXT_VERSION([0.14.1])
AM_GNU_GETTEXT([external])

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
          po/Makefile.in
          src/Makefile
          src/virtManager/Makefile
          src/graphWidgets/Makefile
          virt-manager.spec
	  help/Makefile
	  help/virt-manager/Makefile
	  help/virt-manager/C/Makefile)

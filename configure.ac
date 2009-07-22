
AC_INIT(virt-manager, 0.7.0)
AC_CONFIG_SRCDIR(src/virt-manager.py.in)
dnl Make automake keep quiet about wildcards & other GNUmake-isms
AM_INIT_AUTOMAKE([-Wno-portability])

ALL_LINGUAS="as bg bn_IN bs ca cs da de es fi fr gu hi hr hu is it ja kn ko ml mr ms nb nl or pa pl pt_BR pt ro ru sr@latin sr sv ta te tr uk zh_CN zh_TW"
IT_PROG_INTLTOOL([0.35.0], [no-xml])
AM_GNU_GETTEXT_VERSION([0.14.1])
AM_GNU_GETTEXT([external])

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
          man/Makefile
          tests/Makefile
          virt-manager.spec
          help/Makefile
          help/virt-manager/Makefile
          help/virt-manager/C/Makefile)

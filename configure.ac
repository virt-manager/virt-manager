
AC_INIT(virt-manager, 0.8.5)
# Latest virtinst version required to run
VIRTINST_VERSION="0.500.4"

AC_CONFIG_SRCDIR(src/virt-manager.py.in)
dnl Make automake keep quiet about wildcards & other GNUmake-isms
AM_INIT_AUTOMAKE([-Wno-portability])
AM_MAINTAINER_MODE([enable])

ALL_LINGUAS="as bg bn_IN bs ca cs da de es fi fr gu hi hr hu is it ja kn ko ml mr ms nb nl or pa pl pt_BR pt ro ru sr@latin sr sv ta te tr uk zh_CN zh_TW"
IT_PROG_INTLTOOL([0.35.0], [no-xml])
AM_GNU_GETTEXT_VERSION([0.14.1])
AM_GNU_GETTEXT([external])

dnl ====================================
dnl = Begin tests for scrollkeeper
dnl ====================================
# Help is so outdated, don't even distribute it
#help/Makefile
#help/virt-manager/Makefile
#help/virt-manager/C/Makefile
#AC_PATH_PROG(SCROLLKEEPER_CONFIG, scrollkeeper-config,no)
#if test x$SCROLLKEEPER_CONFIG = xno; then
#  AC_MSG_ERROR(Couldn't find scrollkeeper-config. Please install the scrollkeeper package: http://scrollkeeper.sourceforge.net)
#fi
dnl ====================================
dnl = End tests for scrollkeeper
dnl ====================================


dnl ---------------
dnl Option handling
dnl ---------------
dnl Install TUI
AC_ARG_WITH([tui],
  AC_HELP_STRING(
    [--with-tui],
    [install virt-manager command line interface @<:@default=yes@:>@]),
  [],
  [with_tui=yes])

dnl Default QEMU user
AC_ARG_WITH([qemu-user],
    AC_HELP_STRING(
        [--with-qemu-user],
        [user libvirt uses to launch qemu processes @<:@default=root@:>@]),
    [DEFAULT_QEMU_USER=$withval],
    [DEFAULT_QEMU_USER="root"])

dnl
AC_ARG_ENABLE([unsupported-rhel-options],
  AC_HELP_STRING(
    [--enable-unsupported-rhel-options],
    [enable VM config options unsupported by RHEL @<:@default=yes@:>@]),
  [test "x$enableval" == "xno" && ENABLE_UNSUPPORTED_RHEL_OPTS=0],
  [ENABLE_UNSUPPORTED_RHEL_OPTS=1])


dnl -----------------------
dnl Variable substitution
dnl -----------------------
AC_SUBST([VIRTINST_VERSION])
AC_SUBST([DEFAULT_QEMU_USER])
AC_SUBST([ENABLE_UNSUPPORTED_RHEL_OPTS])
AM_CONDITIONAL([INSTALL_TUI], [test "x$with_tui" = "xyes"])


AC_OUTPUT(Makefile
          pixmaps/Makefile
          pixmaps/hicolor/Makefile
          pixmaps/hicolor/16x16/Makefile
          pixmaps/hicolor/16x16/actions/Makefile
          pixmaps/hicolor/22x22/Makefile
          pixmaps/hicolor/22x22/actions/Makefile
          pixmaps/hicolor/24x24/Makefile
          pixmaps/hicolor/24x24/actions/Makefile
          pixmaps/hicolor/32x32/Makefile
          pixmaps/hicolor/32x32/actions/Makefile
          po/Makefile.in
          src/Makefile
          src/virtManager/Makefile
          src/virtManagerTui/Makefile
          man/Makefile
          tests/Makefile
          virt-manager.spec)


AC_MSG_NOTICE([])
AC_MSG_NOTICE([])

AC_MSG_NOTICE([Required virtinst:               $VIRTINST_VERSION])
AC_MSG_NOTICE([Default qemu user:               $DEFAULT_QEMU_USER])
if test "x$with_tui" = "xyes" ; then
AC_MSG_NOTICE([Install TUI:                     yes])
else
AC_MSG_NOTICE([Install TUI:                     no])
fi
if test "x$ENABLE_UNSUPPORTED_RHEL_OPTS" = "x1" ; then
AC_MSG_NOTICE([Enable unsupported RHEL opts:    yes])
else
AC_MSG_NOTICE([Enable unsupported RHEL opts:    no])
fi

AC_MSG_NOTICE([])
AC_MSG_NOTICE([])

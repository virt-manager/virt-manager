
AC_INIT(virt-manager, 0.9.3)
# Latest virtinst version required to run
VIRTINST_VERSION="0.600.2"

AC_CONFIG_SRCDIR(src/virt-manager.py.in)
dnl Make automake keep quiet about wildcards & other GNUmake-isms
AM_INIT_AUTOMAKE([-Wno-portability])
AM_MAINTAINER_MODE([enable])

ALL_LINGUAS="as bg bn_IN bs ca cs da de es fi fr gu hi hr hu is it ja kn ko ml mr ms nb nl or pa pl pt_BR pt ro ru sr@latin sr sv ta te tr uk zh_CN zh_TW"
IT_PROG_INTLTOOL([0.35.0], [no-xml])
AM_GNU_GETTEXT_VERSION([0.14.1])
AM_GNU_GETTEXT([external])

GETTEXT_PACKAGE=virt-manager
AC_SUBST(GETTEXT_PACKAGE)
AC_DEFINE_UNQUOTED([GETTEXT_PACKAGE],"$GETTEXT_PACKAGE",
                   [GETTEXT package name])

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

dnl Distro libvirt package name
AC_ARG_WITH([libvirt-package-names],
    AC_HELP_STRING(
        [--with-libvirt-package-names],
        [name of libvirt distro packages virt-manager will check for on first run @<:@default=none@:>@]),
    [LIBVIRT_PACKAGES=$withval],
    [LIBVIRT_PACKAGES=""])

dnl Recommended HV packages
AC_ARG_WITH([kvm-packages],
    AC_HELP_STRING(
        [--with-kvm-packages],
        [recommended kvm packages virt-manager will check for on first run @<:@default=none@:>@]),
    [KVM_PACKAGES=$withval],
    [KVM_PACKAGES=""])

dnl askpass package name
AC_ARG_WITH([askpass-package],
    AC_HELP_STRING(
        [--with-askpass-package],
        [name of your distros openssh askpass package@<:@default=none@:>@]),
    [ASKPASS_PACKAGE=$withval],
    [ASKPASS_PACKAGE=""])

dnl Don't list options that rhel doesn't support
AC_ARG_ENABLE([unsupported-rhel-options],
  AC_HELP_STRING(
    [--enable-unsupported-rhel-options],
    [enable VM config options unsupported by RHEL @<:@default=yes@:>@]),
  [test "x$enableval" == "xno" && \
   ENABLE_UNSUPPORTED_RHEL_OPTS=0 ||
   ENABLE_UNSUPPORTED_RHEL_OPTS=1],
  [ENABLE_UNSUPPORTED_RHEL_OPTS=1])

dnl Allow passing in a prefered distro list
AC_ARG_WITH([preferred-distros],
    AC_HELP_STRING(
        [--with-preferred-distros],
        [Distros to list first in New VM wizard @<:@default=none@:>@]),
    [PREFERRED_DISTROS=$withval],
    [PREFERRED_DISTROS=""])

dnl Default graphics type (spice/vnc)
AC_ARG_WITH([default-graphics],
    AC_HELP_STRING(
        [--with-default-graphics],
        [default graphics type for new guests in gconf(spice or vnc) @<:@default=vnc@:>@]),
    [DEFAULT_GRAPHICS=$withval],
    [DEFAULT_GRAPHICS="vnc"])

dnl -----------------------
dnl Variable substitution
dnl -----------------------
AC_SUBST([VIRTINST_VERSION])
AC_SUBST([DEFAULT_QEMU_USER])
AC_SUBST([ENABLE_UNSUPPORTED_RHEL_OPTS])
AC_SUBST([PREFERRED_DISTROS])
AC_SUBST([LIBVIRT_PACKAGES])
AC_SUBST([KVM_PACKAGES])
AC_SUBST([ASKPASS_PACKAGE])
AC_SUBST([DEFAULT_GRAPHICS])
AM_CONDITIONAL([INSTALL_TUI], [test "x$with_tui" = "xyes"])


AC_OUTPUT(Makefile
          po/Makefile.in
          src/Makefile
          src/virtManager/Makefile
          src/virtManagerTui/Makefile
          src/virtManagerTui/importblacklist/Makefile
          man/Makefile
          tests/Makefile
          virt-manager.spec

          icons/Makefile
          icons/hicolor/Makefile
          icons/hicolor/16x16/Makefile
          icons/hicolor/22x22/Makefile
          icons/hicolor/24x24/Makefile
          icons/hicolor/32x32/Makefile
          icons/hicolor/48x48/Makefile
          icons/hicolor/256x256/Makefile
)


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
AC_MSG_NOTICE([Enable unsupported RHEL options: yes])
else
AC_MSG_NOTICE([Enable unsupported RHEL options: no])
fi
if test "x$PREFERRED_DISTROS" = "x" ; then
AC_MSG_NOTICE([Preferred distros:               none])
else
AC_MSG_NOTICE([Preferred distros:               $PREFERRED_DISTROS])
fi
if test "x$LIBVIRT_PACKAGES" = "x" ; then
AC_MSG_NOTICE([Libvirt packages:                none])
else
AC_MSG_NOTICE([Libvirt Packages:                $LIBVIRT_PACKAGES])
fi
if test "x$KVM_PACKAGES" = "x" ; then
AC_MSG_NOTICE([KVM packages:                    none])
else
AC_MSG_NOTICE([KVM packages:                    $KVM_PACKAGES])
fi
if test "x$ASKPASS_PACKAGE" = "x" ; then
AC_MSG_NOTICE([askpass package:                 none])
else
AC_MSG_NOTICE([askpass package:                 $ASKPASS_PACKAGE])
fi
AC_MSG_NOTICE([Default graphics:                $DEFAULT_GRAPHICS])

AC_MSG_NOTICE([])
AC_MSG_NOTICE([])

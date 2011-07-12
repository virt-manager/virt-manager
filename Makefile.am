ACLOCAL_AMFLAGS = -I m4/

SUBDIRS = src icons man po tests

EXTRA_DIST = @PACKAGE@.spec HACKING COPYING-DOCS xmldocs.make omf.make \
	intltool-extract.in intltool-merge.in intltool-update.in

DISTCLEAN_FILES = @PACKAGE@.spec intltool-extract intltool-merge intltool-update

rpm: clean
	$(MAKE) dist && rpmbuild -ta $(distdir).tar.gz

srpm: clean
	$(MAKE) dist && rpmbuild -ts $(distdir).tar.gz

check-pylint:
	tests/pylint-virt-manager.sh

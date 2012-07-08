
SUBDIRS = virtManager

bin_SCRIPTS_IN = virt-manager.in
bin_SCRIPTS = virt-manager

pythondir = $(pkgdatadir)
python_DATA_IN = $(PACKAGE).py.in
python_DATA = $(PACKAGE).py

libexec_DATA_IN = $(PACKAGE)-launch.in
libexec_SCRIPTS = $(PACKAGE)-launch

gladedir = $(pkgdatadir)
glade_DATA = $(wildcard $(srcdir)/*.ui)

desktopdir = $(datadir)/applications
desktop_DATA_IN = $(PACKAGE).desktop.in.in
desktop_DATA = $(PACKAGE).desktop

dbusdir = $(datadir)/dbus-1/services
dbus_DATA_IN = $(PACKAGE).service.in
dbus_DATA = $(PACKAGE).service

schemadir = $(sysconfdir)/gconf/schemas
schema_DATA_IN = $(PACKAGE).schemas.in
schema_DATA = $(PACKAGE).schemas

CLEANFILES = $(bin_SCRIPTS) $(desktop_DATA) $(dbus_DATA) $(python_DATA) $(libexec_SCRIPTS) $(schema_DATA) $(PACKAGE).desktop.in

EXTRA_DIST = $(bin_SCRIPTS_IN) $(desktop_DATA_IN) $(dbus_DATA_IN) $(python_DATA_IN) $(glade_DATA) $(libexec_DATA_IN) $(schema_DATA_IN)

if INSTALL_TUI
SUBDIRS += virtManagerTui

bin_SCRIPTS_IN += virt-manager-tui.in
bin_SCRIPTS += virt-manager-tui

python_DATA_IN += $(PACKAGE)-tui.py.in
python_DATA += $(PACKAGE)-tui.py
endif

@INTLTOOL_DESKTOP_RULE@

%.desktop.in: $(srcdir)/%.desktop.in.in ${top_builddir}/config.status
	sed -e "s,::PACKAGE::,$(PACKAGE)," < $< > $@

%.service: $(srcdir)/%.service.in ${top_builddir}/config.status
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PREFIX::,$(prefix)," < $< > $@

%.schemas: $(srcdir)/%.schemas.in ${top_builddir}/config.status
	sed -e "s|::DEFAULT_GRAPHICS::|$(DEFAULT_GRAPHICS)|g" \
	    -e "s,::PACKAGE::,$(PACKAGE)," \
	    < $< > $@

%.py: $(srcdir)/%.py.in ${top_builddir}/config.status
	sed -e "s,::PACKAGE::,$(PACKAGE)," \
	  -e "s,::VERSION::,$(VERSION)," \
	  -e "s,::ASSETDIR::,$(pkgdatadir)," \
	  -e "s,::PYLIBDIR::,$(pkgdatadir)," \
	  -e "s,::GETTEXTDIR::,$(datadir)/locale," \
	  -e "s,::DATADIR::,$(datadir)," \
	  -e "s,::PYARCHLIBDIR::,$(pkglibdir)," \
	  -e "s,::VIRTINST_VERSION::,$(VIRTINST_VERSION)," \
	  -e "s,::DEFAULT_QEMU_USER::,$(DEFAULT_QEMU_USER)," \
	  -e "s,::ENABLE_UNSUPPORTED_RHEL_OPTS::,$(ENABLE_UNSUPPORTED_RHEL_OPTS)," \
	  -e "s|::PREFERRED_DISTROS::|$(PREFERRED_DISTROS)|" \
	  -e "s|::HV_PACKAGES::|$(KVM_PACKAGES)|" \
	  -e "s|::ASKPASS_PACKAGE::|$(ASKPASS_PACKAGE)|" \
	  -e "s|::LIBVIRT_PACKAGES::|$(LIBVIRT_PACKAGES)|" \
	  < $< > $@

$(PACKAGE): $(srcdir)/$(PACKAGE).in ${top_builddir}/config.status
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@

$(PACKAGE)-tui: $(srcdir)/$(PACKAGE)-tui.in ${top_builddir}/config.status
	sed -e "s,::PACKAGE::,$(PACKAGE)-tui," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@

$(PACKAGE)-launch: $(srcdir)/$(PACKAGE)-launch.in ${top_builddir}/config.status
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@



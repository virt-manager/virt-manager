
SUBDIRS = virtManager

bin_SCRIPTS_IN = virt-manager.in
bin_SCRIPTS = virt-manager

pythondir = $(pkgdatadir)
python_DATA_IN = $(PACKAGE).py.in
python_DATA = $(PACKAGE).py

libexec_DATA_IN = $(PACKAGE)-launch.in
libexec_SCRIPTS = $(PACKAGE)-launch

gladedir = $(pkgdatadir)
glade_DATA = $(wildcard $(srcdir)/*.glade)

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
python_DATA = $(PACKAGE)-tui.py
endif

@INTLTOOL_DESKTOP_RULE@

%.desktop.in: $(srcdir)/%.desktop.in.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::ICONDIR::,$(pkgdatadir)/pixmaps," < $< > $@

%.service: $(srcdir)/%.service.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PREFIX::,$(prefix)," < $< > $@

%.schemas: $(srcdir)/%.schemas.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," < $< > $@

%.py: $(srcdir)/%.py.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," \
	  -e "s,::VERSION::,$(VERSION)," \
	  -e "s,::ASSETDIR::,$(pkgdatadir)," \
	  -e "s,::PYLIBDIR::,$(pkgdatadir)," \
	  -e "s,::GETTEXTDIR::,$(datadir)/locale," \
	  -e "s,::DATADIR::,$(datadir)," \
	  -e "s,::PYARCHLIBDIR::,$(pkglibdir)," \
	  -e "s,::VIRTINST_VERSION::,$(VIRTINST_VERSION)," < $< > $@

$(PACKAGE): $(srcdir)/$(PACKAGE).in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@

$(PACKAGE)-tui: $(srcdir)/$(PACKAGE)-tui.in
	sed -e "s,::PACKAGE::,$(PACKAGE)-tui," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@

$(PACKAGE)-launch: $(srcdir)/$(PACKAGE)-launch.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@



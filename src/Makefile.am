
SUBDIRS = vncViewer graphWidgets virtManager

bin_SOURCES = virt-manager.in
bin_SCRIPTS = virt-manager

pythondir = $(pkgdatadir)
python_SOURCES = $(PACKAGE).py.in
python_DATA = $(PACKAGE).py

libexec_SOURCES = $(PACKAGE)-launch.in
libexec_SCRIPTS = $(PACKAGE)-launch

gladedir = $(pkgdatadir)
glade_DATA = $(PACKAGE).glade

desktopdir = $(datadir)/applications
desktop_SOURCES = $(PACKAGE).desktop.in
desktop_DATA = $(PACKAGE).desktop

dbusdir = $(datadir)/dbus-1/services
dbus_SOURCES = $(PACKAGE).service.in
dbus_DATA = $(PACKAGE).service

schemadir = $(sysconfdir)/gconf/schemas
schema_SOURCES = $(PACKAGE).schemas.in
schema_DATA = $(PACKAGE).schemas

CLEANFILES = $(bin_SCRIPTS) $(desktop_DATA) $(dbus_DATA) $(python_DATA)  $(libexec_SCRIPTS) $(schema_DATA)

EXTRA_DIST = $(bin_SOURCES) $(desktop_SOURCES) $(dbus_SOURCES) $(python_SOURCES) $(glade_DATA) $(libexec_SOURCES) $(schema_SOURCES)


%.desktop: $(srcdir)/%.desktop.in
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
          -e "s,::PYARCHLIBDIR::,$(pkglibdir)," < $< > $@

$(PACKAGE): $(srcdir)/$(PACKAGE).in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@

$(PACKAGE)-launch: $(srcdir)/$(PACKAGE)-launch.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@



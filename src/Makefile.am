
SUBDIRS = virtManager vncViewer graphWidgets

bin_SOURCES = gnome-virt-manager.in
bin_SCRIPTS = gnome-virt-manager

pythondir = $(pkgdatadir)
python_SOURCES = $(PACKAGE).py.in
python_DATA = $(PACKAGE).py

libexec_SOURCES = $(PACKAGE)-launch.in
libexec_SCRIPTS = $(PACKAGE)-launch

gladedir = $(pkgdatadir)
glade_DATA = $(wildcard $(srcdir)/*.glade)

desktopdir = $(datadir)/applications
desktop_SOURCES = $(PACKAGE).desktop.in
desktop_DATA = $(PACKAGE).desktop

dbusdir = $(datadir)/dbus-1/services
dbus_SOURCES = $(PACKAGE).service.in
dbus_DATA = $(PACKAGE).service

CLEANFILES = $(bin_SCRIPTS) $(desktop_DATA) $(dbus_DATA) $(python_DATA)  $(libexec_SCRIPTS)

EXTRA_DIST = $(bin_SOURCES) $(desktop_SOURCES) $(dbus_SOURCES) $(python_SOURCES) $(glade_DATA) $(libexec_SOURCES)


%.desktop: $(srcdir)/%.desktop.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::ICONDIR::,$(pkgdatadir)," < $< > $@

%.service: $(srcdir)/%.service.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PREFIX::,$(prefix)," < $< > $@

%.py: $(srcdir)/%.py.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," \
	  -e "s,::ASSETDIR::,$(pkgdatadir)," \
	  -e "s,::PYLIBDIR::,$(pkgdatadir)," \
          -e "s,::PYARCHLIBDIR::,$(pkglibdir)," < $< > $@

gnome-virt-manager: $(srcdir)/gnome-virt-manager.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@

gnome-virt-manager-launch: $(srcdir)/gnome-virt-manager-launch.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@



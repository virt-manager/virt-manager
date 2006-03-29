
bin_SOURCES = gnome-virt-manager.in
bin_SCRIPTS = gnome-virt-manager

pythondir = $(pkgdatadir)
python_SOURCES = $(PACKAGE).py.in
python_DATA = $(PACKAGE).py

gladedir = $(pkgdatadir)
glade_DATA = $(wildcard $(srcdir)/*.glade)

desktopdir = $(datadir)/applications
desktop_SOURCES = $(PACKAGE).desktop.in
desktop_DATA = $(PACKAGE).desktop

CLEANFILES = $(PACKAGE) $(PACKAGE).py  $(PACKAGE).desktop

EXTRA_DIST = $(bin_SOURCES) $(desktop_SOURCES) $(python_SOURCES) $(glade_DATA)


%.desktop: $(srcdir)/%.desktop.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::ICONDIR::,$(pkgdatadir)," < $< > $@

%.py: $(srcdir)/%.py.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::ASSETDIR::,$(pkgdatadir)," < $< > $@

gnome-virt-manager: $(srcdir)/gnome-virt-manager.in
	sed -e "s,::PACKAGE::,$(PACKAGE)," -e "s,::PYTHONDIR::,$(pkgdatadir)," < $< > $@



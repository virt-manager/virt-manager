#
# No modifications of this Makefile should be necessary.
#
# To use this template:
#     1) Define: figdir, docname, lang, omffile, and entities in
#        your Makefile.am file for each document directory,
#        although figdir, omffile, and entities may be empty
#     2) Make sure the Makefile in (1) also includes 
#	 "include $(top_srcdir)/xmldocs.make" and
#	 "dist-hook: app-dist-hook".
#     3) Optionally define 'entities' to hold xml entities which
#        you would also like installed
#     4) Figures must go under $(figdir)/ and be in PNG format
#     5) You should only have one document per directory 
#     6) Note that the figure directory, $(figdir)/, should not have its
#        own Makefile since this Makefile installs those figures.
#
# example Makefile.am:
#   figdir = figures
#   docname = scrollkeeper-manual
#   lang = C
#   omffile=scrollkeeper-manual-C.omf
#   entities = fdl.xml
#   include $(top_srcdir)/xmldocs.make
#   dist-hook: app-dist-hook
#
# About this file:
#	This file was taken from scrollkeeper_example2, a package illustrating
#	how to install documentation and OMF files for use with ScrollKeeper 
#	0.3.x and 0.4.x.  For more information, see:
#		http://scrollkeeper.sourceforge.net/
#	Version: 0.1.2 (last updated: March 20, 2002)
#


# **********  Begin of section some packagers may need to modify  **********
# This variable (docdir) specifies where the documents should be installed.
# This default value should work for most packages.
docdir = $(datadir)/gnome/help/$(docname)/$(lang)

# **********  You should not have to edit below this line  **********
xml_files = $(entities) $(docname).xml

EXTRA_DIST = $(xml_files) $(omffile)
CLEANFILES = omf_timestamp

include $(top_srcdir)/omf.make

all: omf

$(docname).xml: $(entities)
	-ourdir=`pwd`;  \
	cd $(srcdir);   \
	cp $(entities) $$ourdir

app-dist-hook:
	if test "$(figdir)"; then \
	  $(mkinstalldirs) $(distdir)/$(figdir); \
	  for file in $(srcdir)/$(figdir)/*.png; do \
	    basefile=`echo $$file | sed -e  's,^.*/,,'`; \
	    $(INSTALL_DATA) $$file $(distdir)/$(figdir)/$$basefile; \
	  done \
	fi

install-data-local: omf
	$(mkinstalldirs) $(DESTDIR)$(docdir)
	for file in $(xml_files); do \
	  cp $(srcdir)/$$file $(DESTDIR)$(docdir); \
	done
	if test "$(figdir)"; then \
	  $(mkinstalldirs) $(DESTDIR)$(docdir)/$(figdir); \
	  for file in $(srcdir)/$(figdir)/*.png; do \
	    basefile=`echo $$file | sed -e  's,^.*/,,'`; \
	    $(INSTALL_DATA) $$file $(DESTDIR)$(docdir)/$(figdir)/$$basefile; \
	  done \
	fi

install-data-hook: install-data-hook-omf

uninstall-local: uninstall-local-doc uninstall-local-omf

uninstall-local-doc:
	-if test "$(figdir)"; then \
	  for file in $(srcdir)/$(figdir)/*.png; do \
	    basefile=`echo $$file | sed -e  's,^.*/,,'`; \
	    rm -f $(DESTDIR)$(docdir)/$(figdir)/$$basefile; \
	  done; \
	  rmdir $(DESTDIR)$(docdir)/$(figdir); \
	fi
	-for file in $(xml_files); do \
	  rm -f $(DESTDIR)$(docdir)/$$file; \
	done
	-rmdir $(DESTDIR)$(docdir)

clean-local: clean-local-doc clean-local-omf

# for non-srcdir builds, remove the copied entities.
clean-local-doc:
	if test $(srcdir) != .; then \
	  rm -f $(entities); \
	fi

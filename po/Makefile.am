
MSGMERGE = msgmerge -v
POS = $(wildcard $(srcdir)/*.po)
FMTCATALOGS = $(patsubst $(srcdir)/%.po,%.mo,$(POS))
NLSDIR = $(datadir)/locale

POTFILE = $(srcdir)/$(PACKAGE).pot

GLADEFILES = $(wildcard $(top_srcdir)/src/*.glade)

GLADESCRATCHFILES = $(GLADEFILES:$(top_srcdir)/src/%=tmp/%.h)

POTFILES = $(top_srcdir)/src/*.py.in \
           $(top_srcdir)/src/virtManager/*.py \
           $(top_srcdir)/src/vncViewer/*.py

all: $(FMTCATALOGS)

EXTRA_DIST = $(POTFILE) $(POS)

refresh-pot: $(POTFILES) $(GLADESCRATCHFILES)
	xgettext --default-domain=$(PACKAGE) \
		 --keyword=_ --keyword=N_ $(POTFILES) $(GLADESCRATCHFILES)
	if cmp -s $(PACKAGE).po $(POTFILE); then \
	    rm -f $(PACKAGE).po; \
	else \
	    mv $(PACKAGE).po $(POTFILE); \
	fi

tmp/%.h: $(top_srcdir)/src/%
	rm -f $@
	intltool-extract --type=gettext/glade -l $<

update-po: Makefile refresh-pot refresh-po

refresh-po: Makefile
	for cat in $(POS); do \
		pot=`echo $$cat | sed -e 's/\.po$$/\.pot$$/'`; \
		if $(MSGMERGE) $$cat $(POTFILE) > $$pot ; then \
			mv -f $$pot $$cat ; \
			echo "$(MSGMERGE) of $$cat succeeded" ; \
		else \
			echo "$(MSGMERGE) of $$cat failed" ; \
			rm -f $$pot ; \
		fi \
	done

report:
	@for cat in $(POS); do \
		echo -n "$$cat: "; \
		msgfmt -v --statistics -o /dev/null $$cat; \
	done

CLEANFILES = $(FMTCATALOGS) $(GLADESCRATCHFILES) tmp

install-data-local: $(FMTCATALOGS) 
	mkdir -p $(DESTDIR)$(NLSDIR)
	for n in $(FMTCATALOGS); do \
	    l=`basename $$n .mo`; \
	    $(INSTALL) -m 755 -d $(DESTDIR)$(NLSDIR)/$$l; \
	    $(INSTALL) -m 755 -d $(DESTDIR)$(NLSDIR)/$$l/LC_MESSAGES; \
	    $(INSTALL) -m 644 $$n \
		$(DESTDIR)$(NLSDIR)/$$l/LC_MESSAGES/$(PACKAGE).mo; \
	done

.PHONY: missing-msgs

missing-msgs:
	mkdir -p missing; \
	for n in $(FMTCATALOGS); do \
	    msghack -w 999999 --missing $$n > missing/$$n-; \
            msghack -w 999999 --empty missing/$$n- | grep -v "^#," > missing/$$n; \
	    rm missing/$$n-; \
	done

missing-mixed:
	mkdir -p missing-mixed; \
	for n in $(FMTCATALOGS); do \
	    msghack -w 999999 --missing $$n > missing-mixed/$$n; \
	done

%.mo: %.po
	msgfmt --check -o $@ $<

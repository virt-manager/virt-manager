pythondir = $(pkgdatadir)/virtManagerTui/importblacklist
python_DATA = $(wildcard $(srcdir)/*.py)

EXTRA_DIST = $(python_DATA)

SYNTAX_CHECK_TSTAMPS = $(python_DATA:$(srcdir)/%.py=.tstamp.%.py)


check-local: $(SYNTAX_CHECK_TSTAMPS)

clean-local:
	rm -f $(SYNTAX_CHECK_TSTAMPS)

.tstamp.%.py: %.py
	touch $@

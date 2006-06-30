
sparklinedir = $(pkglibdir)
sparkline_LTLIBRARIES = sparkline.la

CODEGENDIR := $(shell pkg-config --variable=codegendir pygtk-2.0)
DEFSDIR :=  $(shell pkg-config --variable=defsdir pygtk-2.0)

pysparklinemodule.defs: sparkline.h cellrenderersparkline.h
	python $(CODEGENDIR)/h2def.py $^ > $@

pysparklinemodule.c: pysparklinemodule.defs pysparklinemodule.override
	pygtk-codegen-2.0 \
        --prefix sparkline \
	--register $(DEFSDIR)/gdk-types.defs \
	--register $(DEFSDIR)/gtk-types.defs \
	--override $(srcdir)/pysparklinemodule.override \
	pysparklinemodule.defs > $@

sparkline_la_SOURCES = \
    sparklinemodule.c \
    pysparklinemodule.c \
    cellrenderersparkline.c \
    cellrenderersparkline.h \
    sparkline.c \
    sparkline.h

sparkline_la_CFLAGS = -fPIC -Wall \
    $(PYGTK2_CFLAGS) \
    $(GTK2_CFLAGS) \
    $(PYTHON_CPPFLAGS)

sparkline_la_LIBADD = \
    $(PYGTK2_LIBS) \
    $(GTK2_LIBS) \
    $(PYTHON_LDFLAGS)

sparkline_la_LDFLAGS = -module -avoid-version -fPIC

EXTRA_DIST = pysparklinemodule.override

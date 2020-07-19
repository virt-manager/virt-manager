# -*- rpm-spec -*-

%global with_guestfs               0
%global default_hvs                "qemu,xen,lxc"


# End local config

Name: virt-manager
Version: 2.2.1
Release: 1%{?dist}
%global verrel %{version}-%{release}

Summary: Desktop tool for managing virtual machines via libvirt
License: GPLv2+
BuildArch: noarch
URL: https://virt-manager.org/
Source0: https://virt-manager.org/download/sources/%{name}/%{name}-%{version}.tar.gz


Requires: virt-manager-common = %{verrel}
Requires: python3-gobject
Requires: gtk3
Requires: libvirt-glib >= 0.0.9
Requires: gtk-vnc2
Requires: spice-gtk3

# We can work with gtksourceview 3 or gtksourceview4, pick the latest one
Requires: gtksourceview4

# virt-manager is one of those apps that people will often install onto
# a headless machine for use over SSH. This means the virt-manager dep
# chain needs to provide everything we need to get a usable app experience.
# Unfortunately nothing in our chain has an explicit dep on some kind
# of usable gsettings backend, so we explicitly depend on dconf so that
# user settings actually persist across app runs.
Requires: dconf

# The vte291 package is actually the latest vte with API version 2.91, while
# the vte3 package is effectively a compat package with API version 2.90.
# virt-manager works fine with either, so pull the latest bits so there's
# no ambiguity.
Requires: vte291

# Weak dependencies for the common virt-manager usecase
Recommends: (libvirt-daemon-kvm or libvirt-daemon-qemu)
Recommends: libvirt-daemon-config-network

# Optional inspection of guests
Suggests: python3-libguestfs

BuildRequires: gettext
BuildRequires: /usr/bin/pod2man
BuildRequires: python3-devel


%description
Virtual Machine Manager provides a graphical tool for administering virtual
machines for KVM, Xen, and LXC. Start, stop, add or remove virtual devices,
connect to a graphical or serial console, and see resource usage statistics
for existing VMs on local or remote machines. Uses libvirt as the backend
management API.


%package common
Summary: Common files used by the different Virtual Machine Manager interfaces

Requires: python3-argcomplete
Requires: python3-libvirt
Requires: python3-libxml2
Requires: python3-requests
Requires: libosinfo >= 0.2.10
# Required for gobject-introspection infrastructure
Requires: python3-gobject-base
# Required for pulling files from iso media with isoinfo
Requires: genisoimage

%description common
Common files used by the different virt-manager interfaces, as well as
virt-install related tools.


%package -n virt-install
Summary: Utilities for installing virtual machines

Requires: virt-manager-common = %{verrel}
# For 'virsh console'
Requires: libvirt-client

Provides: virt-install
Provides: virt-clone
Provides: virt-xml

%description -n virt-install
Package includes several command line utilities, including virt-install
(build and install new VMs) and virt-clone (clone an existing virtual
machine).


%prep
%setup -q


%build
%if %{default_hvs}
%global _default_hvs --default-hvs %{default_hvs}
%endif

./setup.py configure \
    %{?_default_hvs}


%install
./setup.py \
    --no-update-icon-cache --no-compile-schemas \
    install -O1 --root=%{buildroot}
%find_lang %{name}

%if 0%{?py_byte_compile:1}
# https://docs.fedoraproject.org/en-US/packaging-guidelines/Python_Appendix/#manual-bytecompilation
%py_byte_compile %{python3} %{buildroot}%{_datadir}/virt-manager/
%endif

# Replace '#!/usr/bin/env python3' with '#!/usr/bin/python3'
# The format is ideal for upstream, but not a distro. See:
# https://fedoraproject.org/wiki/Features/SystemPythonExecutablesUseSystemPython
for f in $(find %{buildroot} -type f -executable -print); do
    sed -i "1 s|^#!/usr/bin/env python3|#!%{__python3}|" $f || :
done


%files
%doc README.md COPYING NEWS.md
%{_bindir}/%{name}

%{_mandir}/man1/%{name}.1*

%{_datadir}/%{name}/ui/*.ui
%{_datadir}/%{name}/virtManager

%{_datadir}/%{name}/icons
%{_datadir}/icons/hicolor/*/apps/*

%{_datadir}/applications/%{name}.desktop
%{_datadir}/glib-2.0/schemas/org.virt-manager.virt-manager.gschema.xml
%{_datadir}/metainfo/%{name}.appdata.xml


%files common -f %{name}.lang
%dir %{_datadir}/%{name}

%{_datadir}/%{name}/virtinst


%files -n virt-install
%{_mandir}/man1/virt-install.1*
%{_mandir}/man1/virt-clone.1*
%{_mandir}/man1/virt-xml.1*

%{_datadir}/bash-completion/completions/virt-install
%{_datadir}/bash-completion/completions/virt-clone
%{_datadir}/bash-completion/completions/virt-xml

%{_bindir}/virt-install
%{_bindir}/virt-clone
%{_bindir}/virt-xml

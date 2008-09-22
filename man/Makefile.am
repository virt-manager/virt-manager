
man_MANS = virt-manager.1

EXTRA_DIST = virt-manager.pod

%.1: %.pod
	pod2man --center="Virtual Machine Manager" $< > $@

CLEANFILES = virt-manager.1

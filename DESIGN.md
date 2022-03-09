##  virt-manager UI design philosophy

**virt-manager** is a UI toolbox-style frontend for libvirt. It provides UI access to common virt management tasks and operations. virt-manager aims to provide a simple UI, but not too simple that it excludes valid usecases. virt-manager prioritizes stability over features. Given the user definitions defined below, our goals are:

* **_Basic virt users_** should be able to meet their needs with virt-manager.
* **_Intermediate virt users_** should find virt-manager sufficiently flexible for their needs.
* **_Advanced virt users_** will not find explicit UI support for their advanced use cases, but virt-manager should still function correctly in the face of their manually configured advanced virt usage. virt-manager should not get in their way.

Here are some things that virt-manager explicitly is not:

* **gnome-boxes**: a heavily desktop integrated VM manager with an emphasis on UI design and simplifying virt management. They prioritize a seamless designed experience over flexibility, our goals are different.
* **virt-viewer/remote-viewer**, **vncviewer**: our graphical VM window should 'just work' for most needs but any advanced console configuration is left up to these other better suited tools.
* **VirtualBox**, **VMWare Workstation**: It's a nice idea to aim to be the equivalent of those apps for the QEMU+KVM+Libvirt stack. But to get there would require a level of resource investment that is unlikely to ever happen.
* **oVirt**, **Openstack**: virt-manager does not aim to support management of many hosts with many VMs. virt-manager won't reject this case and we try within reason to keep it working. But the UI is not designed for it and we will not change the UI to facilitate these style of usecases.

## How do we evaluate UI changes

When is it worth it to expose something in the UI? Here's some criteria we will use:

* **How many users do we expect will use it**: This is handwavy of course but some things come up in email/IRC discussion regularly, and some are mentioned once in 5 years.

* **How critical is it for users who need/want it**: if it's an absolute blocker just to get a working config for some people, that can influence the discussion

* **How self explanatory is the feature**: 'Enable 3D acceleration' is fairly self explanatory. Disk io native vs threads, not so much.

* **How dangerous or difficult to use is the feature**: If it works in only specific cases or renders the VM unbootable for certain scenarios, this matters.

* **How much work is it to maintain, test**

* **How much work is it to implement**: If something requires significant app specific logic on top of libvirt, libosinfo, or spice-gtk that would also be useful to other virt apps, it is suspect. We should be aiming to share common functionality


## User definitions

### Basic virt user

They know little or nothing about libvirt, qemu, and kvm, but they understand the high level concept of a virtual machine. They have a Windows or Linux distro ISO and they want to create a VM and interact with it graphically. They should be able to figure out how to do that by running virt-manager and following the UI. The defaults we provide for new VMs should be sufficient for their needs.

After the VM is installed, the UI should facilitate intuitive UI tasks like:

* lifecycle operations: start/stop/pause the VM; save, snapshot the VM; delete, clone the VM
* rename the VM; change the VM title or description
* eject/insert CDROM media; change VM boot order
* increase VM memory
* attach a host USB device to the VM; possibly add an additional disk to the VM
* graphical operations like send a keycombo, screenshot

### Intermediate virt user

They know more about virt in general but we do not assume they have ever edited libvirt XML or run the qemu command line. They are a more intermediate tech user anyways. They may know about less standard virt features and they want to enable them for their VMs. Or they are using VMs as part of a specific workflow, possibly for a development environment, or hosting personal services on their own network, or managing VMs on a remote host. This is the fuzzy area. We want to support these people but each request needs to be handled on a case by case basis.

Here's some of the things the current UI supports that fit this bucket:

* Management of remote virt hosts
* Management of non-qemu/kvm libvirt drivers: lxc, vz, xen, bhyve
* Support for non-x86 VM creation: aarch64, armv7l, ppc64, s390x
* Change VM CPU model or mode
* UEFI config for new VMs
* VM direct kernel/initrd boot
* VM serial console access
* VM use of network bridge or macvtap
* Spice/virgl 3D acceleration usage
* Libvirt storage pool management
* Libvirt virtual network management
* Ideally every VM UI edit operation should be justifiable in this context

### Advanced virt user or usecase

An advanced virt user likely has some experience with libvirt XML or the qemu command line. They may know that they need some specific libvirt XML value for their VMs. They may be running virt in an environment that depends on non-trivial non-standard host configuration.

We want virt-manager to still be useful to these users for fulfilling basic and intermediate needs, but not get in the way or prevent usage of their advanced config, within reason.

Some examples:

* **usecase**: managing many hosts and many VMs
* **usecase**: require tweaking anything but the most standard <domain> performance options
* **usecase**: generally anything that requires special host or guest configuration outside virt-manager
* **user**: Generally anybody that knows the qemu command line or specific XML config options they want


## Previously rejected/removed UI elements

* VM properties
  * [disk driver io=threads|native](https://github.com/virt-manager/virt-manager/commit/a162a3b845eee24f66baf63b3aeb82523b274b0d)
  * [disk scsi reservations](https://github.com/virt-manager/virt-manager/commit/b583ea7e66cd0b7117971cf55365355f78dd3670)
  * [disk detect_zeroes](https://github.com/virt-manager/virt-manager/commit/8377b7f7b69ed0716fbe2c2818979a273bcb7567)
  * [graphics spice TLS port](https://github.com/virt-manager/virt-manager/commit/bd82ef65292cc47cffc27b8f67d7987679c61bf3)
  * [graphics keymap selection](https://github.com/virt-manager/virt-manager/commit/7251ea25c2936b69284366abc787f1b33c199b15)
  * [network virtualport](https://github.com/virt-manager/virt-manager/commit/b4b497e28f3f3e32a05f4cf78c21f07022ee824b)
  * [Any explicit `<clock>`/`<timer>` config](https://www.redhat.com/archives/virt-tools-list/2019-January/thread.html#00041)
  * [Raw `<genid>` config](https://www.redhat.com/archives/virt-tools-list/2019-April/msg00001.html)
  * [Fine grained `<cpu><feature>` config](https://www.redhat.com/archives/virt-tools-list/2014-January/msg00180.html)
  * [Host network management via libvirt interface APIs](https://blog.wikichoon.com/2019/04/host-network-interfaces-panel-removed.html)
  * [VM hugepages/hugetlbfs](https://bugzilla.redhat.com/show_bug.cgi?id=1688641)
  * Most VM tuning: `<cputune>`, `<blkiotune>`, `<numatune>`, fine grained `<vcpus>` listing
  * Editing existing machine type/arch/ostype, UEFI config. Only advanced users can make it work, and they can edit the XML.

* Defaults
  * [Defaulting to sky high maxmem and maxvcpus](https://github.com/virt-manager/virt-manager/issues/141)

* Tight desktop integration stuff: registering as a default file handler, registering as a gnome search provider, etc. This is gnome-boxes territory
* Serial console config options like [buffer scrollback size](https://bugzilla.redhat.com/show_bug.cgi?id=1610165). Use `virsh console` or cli tools if need flexibility.

* Advanced VNC/SPICE viewer config. virt-viewer should be the target app
  * VNC bit depth config
  * advanced mouse/keyboard grab support
  * advanced SPICE viewer options
  * [hiding viewer window borders/decorations](https://www.redhat.com/archives/virt-tools-list/2019-January/msg00000.html) [(and another)](https://github.com/virt-manager/virt-manager/pull/233)
  * [hiding window menu bar](https://bugzilla.redhat.com/show_bug.cgi?id=1091311)
  * [keypress delay](https://bugzilla.redhat.com/show_bug.cgi?id=1410943)
  * [SPICE/QXL multidisplay support](https://bugzilla.redhat.com/show_bug.cgi?id=885806)
  * support for [manual key combinations](https://bugzilla.redhat.com/show_bug.cgi?id=1014666), or adding custom values.
  * Any feature that goes beyond what virt-viewer or other clients provide. virt-manager should not be the home for clever console/viewer behavior

* UI scalability features to manage large amounts of VMs
  * [custom manager columns for VM organizing](https://www.redhat.com/archives/virt-tools-list/2019-April/msg00059.html)
  * [organizing VMs into collections/groups](https://bugzilla.redhat.com/show_bug.cgi?id=1193303) ([and another](https://bugzilla.redhat.com/show_bug.cgi?id=1548879))
  * multiselect operations on VMs/other objects ([like storage](https://bugzilla.redhat.com/show_bug.cgi?id=1698879))
  * hiding offline VMs or other view options
  * [Advanced VM name search support](https://github.com/virt-manager/virt-manager/issues/147). Note: GTK provides some support already: in the manager window, CTRL+F to open a searchbox, searches match from the beginning of VMs only, use arrow keys to jump between matches. Use VM 'title' field to customize how it is named in the manager window.


## Use of the bug tracker

We plan to keep open bugs only for:

* bugs/problems that are actively affecting users, which the developers plan to fix eventually.
* features/improvements that the developers plan to implement eventually.

The bug tracker will not be used as a wishlist. Users are free to
file RFEs there, but they may be closed.

* A feature/enhancement request that does not match the design guidelines, will be CLOSED->WONTFIX, with an explanation
* A feature/enhancement request that would be nice to have but the developers do not plan to fix, will be CLOSED->DEFERRED, with an explanation.


## References

* [The original mailing list thread for this document](https://www.redhat.com/archives/virt-tools-list/2019-June/msg00108.html)
* [Follow on discussion about some feature removals](https://www.redhat.com/archives/virt-tools-list/2019-June/msg00117.html), [and a follow up](https://www.redhat.com/archives/virt-tools-list/2019-July/msg00005.html)

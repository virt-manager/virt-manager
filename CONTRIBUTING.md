# Contribute to virt-manager

## Bug reporting

The preferred place for bug reports is bugzilla.redhat.com. This
is documented more at https://virt-manager.org/bugs/

Small issues can be reported in the
[github issue tracker](https://github.com/virt-manager/virt-manager/issues).
Anything that's non-trivial, or is a feature request, should be filed in
bugzilla.

Please only file issues if they apply to the latest version of
virt-manager. If you are using an older version from a distro,
please file a bug with them.

When filing a bug, please reproduce the issue with the `--debug`
flag passed to the tool and attach the full output in the bug
report.


## Writing patches

The following commands will be useful for anyone writing patches:

```sh
./setup.py test      # Run local unit test suite
./setup.py pylint    # Run pylint/pycodestyle checking
```

Any patches shouldn't change the output of 'test' or 'pylint'. Depending
on what version of libvirt or pylint is installed, you may see some
pre-existing errors from these commands. The important thing is that
any changes you make do not add additional errors.

The 'pylint' command requires [`pylint`](https://github.com/PyCQA/pylint)
and [`pycodestyle`](https://github.com/pycqa/pycodestyle) to be installed.
If [`codespell`](https://github.com/codespell-project/codespell) is installed,
it will be invoked as well.

One useful way to manually test virt-manager's UI is using libvirt's
unit test driver. From the source directory, Launch virt-manager like:
```sh
./virt-manager --connect test://$PWD/tests/testdriver.xml
```

This testdriver has many fake XML definitions that can be used to see each bit
of virt-manager's UI. It also enables testing the various wizards without
having to alter your host virt config.

The command line tools can be tested similarly. To run a virt-install
command that won't alter your host config, you can do:

```sh
./virt-install --connect test:///default --debug ...
```

`--connect test:///default` here is libvirt's built in unit test driver.

We use [glade-3](https://glade.gnome.org/) for building most of virt-manager's
UI. See the files in the ui/ directory.


## Submitting patches

The [virt-manager git repo](https://github.com/virt-manager/virt-manager)
is hosted on github. Small patches are acceptable via github pull-request,
but anything non-trivial should be sent to the
[virt-tools-list mailing list](https://www.redhat.com/mailman/listinfo/virt-tools-list).

Sending patches using `git send-email` is preferred, but `git format-patch`
output attached to an email is also fine.


## Introductory tasks

Extending the virt-install or virt-xml command line is a good introductory
task for virt-manager. See [the wiki](https://github.com/virt-manager/virt-manager/wiki)
for both a patch tutorial, and a list of libvirt `<domain>` XML options
that still need to be added to our command line.


## Translations

Translations are handled at `fedora.zanata.org`. Please register for a Fedora
account and request access to a translation team, as described at
[Translate on Zanata](https://fedoraproject.org/wiki/L10N/Translate_on_Zanata),
and contribute at
[virt-manager at Zanata](https://fedora.zanata.org/project/view/virt-manager/).


## Advanced testing

There's a few standalone specialty tests:

```sh
./setup.py test_ui              # dogtail UI test suite. This takes over your desktop
./setup.py test_urls            # Test fetching media from live distro URLs
./setup.py test_initrd_inject   # Test live virt-install --initrd-inject
```

All test 'test*' commands have a `--debug` option if you are hitting problems. For more options, see `./setup.py test --help`.

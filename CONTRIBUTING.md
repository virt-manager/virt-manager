# Contribute to virt-manager

## Bug reporting

We use our [github issue tracker](https://github.com/virt-manager/virt-manager/issues)
for bug reporting. Previously we used bugzilla.redhat.com but nowadays
github is preferred.

Please only file issues if they apply to the latest version of
virt-manager. If you are using an older version from a distro,
please file a bug in your distro's bug tracker..

When filing a bug, please reproduce the issue with the `--debug`
flag passed to the tool and attach the full output in the bug
report.


## Writing patches

The following commands will be useful for anyone writing patches:

```sh
pytest               # Run local unit test suite
./setup.py pylint    # Run pylint/pycodestyle checking
```

Any patches shouldn't change the output of 'pytest' or 'pylint'. Depending
on what version of libvirt or pylint is installed, you may see some
pre-existing errors from these commands. The important thing is that
any changes you make do not add additional errors.

The 'pylint' command requires [`pylint`](https://github.com/PyCQA/pylint)
and [`pycodestyle`](https://github.com/pycqa/pycodestyle) to be installed.
If [`codespell`](https://github.com/codespell-project/codespell) is installed,
it will be invoked as well.

Patches to `virtinst/` code should ideally not regress code coverage
testing. Run `pytest --cov` to see a coverage report
before and after your contribution, and ensure no new lines show up.
Maintainers can help you out if you aren't sure how to test your code.

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


## UI design

If you are planning to add a feature to virt-manager's UI, please read
[DESIGN.md](DESIGN.md) first. Features that do not fit the goals specified
in that document may be rejected. If you are unsure if your feature is a
good fit for virt-manager, please ask on the mailing list before you start
coding!


## Introductory tasks

Extending the virt-install or virt-xml command line is a good introductory
task for virt-manager. See [the wiki](https://github.com/virt-manager/virt-manager/wiki)
for both a patch tutorial, and a list of libvirt `<domain>` XML options
that still need to be added to our command line.


## Translations

Translations are handled through the Weblate instance hosted by the Fedora Project.

* https://translate.fedoraproject.org/projects/virt-manager/virt-manager/
* More info about translating as part of Fedora: https://fedoraproject.org/wiki/L10N/Translate_on_Weblate
* The up to date translation `.pot` template is stored in the [`translations` branch](https://github.com/virt-manager/virt-manager/tree/translations) and synced with the `master` branch before release.


## Advanced testing

There's a few standalone specialty tests:

```sh
pytest --uitests                # dogtail UI test suite. This takes over your desktop
pytest tests/test_urls.py       # Test fetching media from live distro URLs
pytest tests/test_inject.py     # Test live virt-install --initrd-inject
```

To see full debug output from test runs, use
`pytest --capture=no --log-level=debug ...`

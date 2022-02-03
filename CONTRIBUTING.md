# Contribute to virt-manager

## Run code from git

Generally virt-* tools can be run straight from git. For example
for virt-manager:

```
git clone https://github.com/virt-manager/virt-manager
cd virt-manager
./virt-manager --debug
```

The other tools like `virt-install` should work similarly. This
expects you already have a distro provided version of virt-manager
installed which pulled in all the necessary dependencies. If not,
see [INSTALL.md](INSTALL.md) for more hints about finding the
correct dependencies.

## Bug reporting

Bug reports should go to our [github issue tracker](https://github.com/virt-manager/virt-manager/issues).

The bug tracker is for issues affecting the latest code only.
If you are using a distro provided package like from Ubuntu or
Fedora, please file a bug in their bug tracker.

If you suspect the bug also affects upstream code, please confirm
it by running the latest code using the steps above.


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
* The up to date translation `.pot` template is stored in the [`translations` branch](https://github.com/virt-manager/virt-manager/tree/translations) and synced with the `main` branch before release.


## Advanced testing

There's a few standalone specialty tests:

```sh
pytest --uitests                # dogtail UI test suite. This takes over your desktop
pytest tests/test_urls.py       # Test fetching media from live distro URLs
pytest tests/test_inject.py     # Test live virt-install --initrd-inject
```

To see full debug output from test runs, use
`pytest --capture=no --log-level=debug ...`

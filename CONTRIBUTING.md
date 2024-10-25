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
meson test -C build
```

Any patches shouldn't change the output of 'pytest' or 'pylint'. Depending
on what version of libvirt or pylint is installed, you may see some
pre-existing errors from these commands. The important thing is that
any changes you make do not add additional errors.

The 'test' command requires [`pylint`](https://github.com/PyCQA/pylint),
[`pycodestyle`](https://github.com/pycqa/pycodestyle) and
['pytest'](https://github.com/pytest-dev/pytest/) to be installed.
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
is hosted on github. All patches should be submitted there.


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
* The up to date translation `.pot` template is stored in the `main` branch
* Translations are submitted by Weblate as pull requests, usually merged to the
  `main` branch before release and whenever needed (e.g. before updating the
  `.pot` template)


## Advanced testing

There's a few standalone specialty tests:

```sh
pytest --uitests                # dogtail UI test suite. This takes over your desktop
pytest tests/test_urls.py       # Test fetching media from live distro URLs
pytest tests/test_inject.py     # Test live virt-install --initrd-inject
```

To see full debug output from test runs, use
`pytest --capture=no --log-level=debug ...`

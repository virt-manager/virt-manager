# HACKING

The following commands will be useful for anyone writing patches:
```sh
python setup.py test      # Run local unit test suite
python setup.py pylint    # Run a pylint script against the codebase
```

Any patches shouldn't change the output of 'test' or 'pylint'. The
'pylint' requires `pylint` and `pycodestyle` to be installed.

Our pylint script uses a blacklist rather than a whitelist approach,
so it could throw some false positives or useless messages. If you think
your patch exposes one of these, bring it up on the mailing list.

If `python-coverage` is installed, you can run `coverage -r` after
`python setup.py test` finished to see a code coverage report.

'test*' have a `--debug` option if you are hitting problems.
For more options, use `python setup.py test --help`.

One useful way to manually test virt-manager's UI is using libvirt's
unit test driver. From the source directory, Launch virt-manager like:
```sh
virt-manager --connect test://$PWD/tests/testdriver.xml
```

This testdriver has many fake XML definitions that can be used to see each bit
of virt-manager's UI. It also enables testing the various wizards without
having to alter your host virt config.

Also, there's a few standalone specialty tests:
```sh
python setup.py test_urls            # Test fetching media from distro URLs
python setup.py test_initrd_inject   # Test --initrd-inject
```

We use [glade-3](https://glade.gnome.org/) for building virt-manager's UI.
It is recommended you have a fairly recent version of `glade-3`. If a small UI
change seems to rewrite the entire glade file, you likely have a too old
(or too new :) glade version.

## Submitting patches

Patches should be developed against a git checkout and **not** a source
release(see [git repository](https://github.com/virt-manager/virt-manager)).

Patches should be sent to the
[mailing list](http://www.redhat.com/mailman/listinfo/virt-tools-list).

Using git format-patch/send-email is preferred, but an attachment with
format-patch output is fine too.

Small patches are acceptable via github pull-request, but anything
non-trivial should be sent to the mailing list.

## Translations

Translations are handled at `fedora.zanata.org`. Please register for a Fedora
account and request access to a translation team, as described at
[Translate on Zanata](http://fedoraproject.org/wiki/L10N/Translate_on_Zanata).

And contribute to
[virt-manager at Zanata](https://fedora.zanata.org/project/view/virt-manager/).

virtinst_sources = files(
  '__init__.py',
  '_progresspriv.py',
  'buildconfig.py',
  'capabilities.py',
  'cli.py',
  'cloner.py',
  'connection.py',
  'diskbackend.py',
  'domcapabilities.py',
  'generatename.py',
  'guest.py',
  'logger.py',
  'network.py',
  'nodedev.py',
  'osdict.py',
  'pollhelpers.py',
  'progress.py',
  'snapshot.py',
  'storage.py',
  'support.py',
  'uri.py',
  'virtclone.py',
  'virtinstall.py',
  'virtxml.py',
  'xmlapi.py',
  'xmlbuilder.py',
  'xmlutil.py',
)

install_data(
  virtinst_sources,
  install_dir: pkgdir / 'virtinst',
)

subdir('devices')
subdir('domain')
subdir('install')

conf = configuration_data()
conf.set('version', meson.project_version())
conf.set('prefix', prefix)
conf.set('default_graphics', get_option('default-graphics'))
conf.set('default_hvs', ','.join(get_option('default-hvs')))

configure_file(
  input: 'build.cfg.in',
  output: 'build.cfg',
  configuration: conf,
  install: true,
  install_dir: pkgdir / 'virtinst',
)

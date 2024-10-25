virtmanager_sources = files(
  '__init__.py',
  'about.py',
  'addhardware.py',
  'asyncjob.py',
  'baseclass.py',
  'clone.py',
  'config.py',
  'connection.py',
  'connmanager.py',
  'createconn.py',
  'createnet.py',
  'createpool.py',
  'createvm.py',
  'createvol.py',
  'delete.py',
  'engine.py',
  'error.py',
  'host.py',
  'hostnets.py',
  'hoststorage.py',
  'manager.py',
  'migrate.py',
  'oslist.py',
  'preferences.py',
  'storagebrowse.py',
  'systray.py',
  'virtmanager.py',
  'vmmenu.py',
  'vmwindow.py',
  'xmleditor.py',
)

install_data(
  virtmanager_sources,
  install_dir: pkgdir / 'virtManager',
)

subdir('details')
subdir('device')
subdir('lib')
subdir('object')

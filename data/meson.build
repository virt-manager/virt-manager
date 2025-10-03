fs = import('fs')

desktop_file = files('virt-manager.desktop.in')

metainfo_file = files('org.virt_manager.virt-manager.metainfo.xml.in')

install_data(
  'org.virt-manager.virt-manager.gschema.xml',
  install_dir: datadir / 'glib-2.0' / 'schemas',
)

bash_completion_template = files('bash-completion.sh.in')

foreach script: ['virt-install', 'virt-clone', 'virt-xml']
  name = fs.name(script)
  configure_file(
    input: bash_completion_template,
    output: name,
    configuration: {'SCRIPTNAME': name},
    install: true,
    install_dir: datadir / 'bash-completion' / 'completions',
  )
endforeach

subdir('icons')

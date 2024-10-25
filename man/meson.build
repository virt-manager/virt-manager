rst_files = files(
  'virt-install.rst',
  'virt-clone.rst',
  'virt-xml.rst',
  'virt-manager.rst',
)

rst2man_prog = find_program(['rst2man', 'rst2man.py'], required: true)

foreach rst_file : rst_files
  man_page = custom_target(
    input: rst_file,
    output: '@BASENAME@.1',
    command: [ rst2man_prog, '--strict', '@INPUT@', '@OUTPUT@'],
    install: true,
    install_dir: datadir / 'man' / 'man1',
  )
endforeach

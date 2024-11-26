project('virt-manager',
  version: '5.0.0',
  meson_version: '>=0.63.0',
)

python = import('python')
python3 = python.find_installation('python3')

prefix = get_option('prefix')
datadir = prefix / get_option('datadir')
bindir = prefix / get_option('bindir')
pkgdir = datadir / 'virt-manager'

# figure out if we are building from git
git = run_command('test', '-e', '.git', check: false).returncode() == 0

subdir('scripts')
subdir('man')
subdir('data')
subdir('ui')
subdir('virtinst')
subdir('virtManager')
subdir('po')

bin_data = [
  {'pkgname': 'virtinst', 'filename': 'virtinstall', 'toolname': 'virt-install'},
  {'pkgname': 'virtinst', 'filename': 'virtclone', 'toolname': 'virt-clone'},
  {'pkgname': 'virtinst', 'filename': 'virtxml', 'toolname': 'virt-xml'},
  {'pkgname': 'virtManager', 'filename': 'virtmanager', 'toolname': 'virt-manager'},
]

foreach bin : bin_data
  custom_target(
    command: [make_bin_wrapper_prog, pkgdir, bin['pkgname'], bin['filename']],
    capture: true,
    output: bin['toolname'],
    install: true,
    install_dir: bindir,
    install_mode: 'rwxr-xr-x',
  )
endforeach

gnome = import('gnome')
gnome.post_install(
  glib_compile_schemas: get_option('compile-schemas'),
  gtk_update_icon_cache: get_option('update-icon-cache'),
)

if git
  spec_conf = configuration_data({
    'VERSION': meson.project_version(),
  })

  spec_file = configure_file(
    input: 'virt-manager.spec.in',
    output: '@BASENAME@',
    configuration: spec_conf,
  )

  meson.add_dist_script(meson_dist_prog.full_path(), spec_file)
endif

if get_option('tests').auto()
  use_tests = git
elif get_option('tests').enabled()
  use_tests = true
else
  use_tests = false
endif

if use_tests
  subdir('tests')
endif

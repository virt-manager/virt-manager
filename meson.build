project('virt-manager',
  version: '4.1.0',
  meson_version: '>=0.63.0',
)

python = import('python')
python3 = python.find_installation('python3')

prefix = get_option('prefix')
datadir = prefix / get_option('datadir')

# figure out if we are building from git
git = run_command('test', '-e', '.git', check: false).returncode() == 0

subdir('scripts')
subdir('man')
subdir('data')

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

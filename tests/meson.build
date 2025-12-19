lint_files = [
  'tests',
  'virtinst',
  'virtManager',
]

spell_files = lint_files + [
  '*.md',
  'man/*.rst',
  'data/org.virt-manager.virt-manager.gschema.xml',
  'data/org.virt_manager.virt-manager.metainfo.xml.in',
  'data/virt-manager.desktop.in',
  'virt-manager.spec.in',
]

pylint_prog = find_program(['pylint', 'pylint-3'])
# meson sets this MALLOC_PERTURB_ to random value by default but it
# doesn't work correctly with pylint so we need to override it
nomalloc = environment({'MALLOC_PERTURB_': '0'})
test(
  'pylint',
  pylint_prog,
  args: [
    lint_files,
    '--rcfile', '.pylintrc',
  ],
  env: nomalloc,
  workdir: meson.project_source_root(),
  timeout: 300,
)

pytest_prog = find_program(['pytest', 'pytest-3'])
test(
  'pytest',
  pytest_prog,
  workdir: meson.project_source_root(),
  timeout: 300,
)

codespell_prog = find_program('codespell', required:false)
if codespell_prog.found()
  test(
    'codespell',
    codespell_prog,
    args: [
      spell_files,
    ],
    workdir: meson.project_source_root(),
  )
endif

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

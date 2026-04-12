i18n = import('i18n')

i18n.merge_file(
  input: desktop_file,
  output: '@BASENAME@',
  type: 'desktop',
  po_dir: meson.current_source_dir(),
  install: true,
  install_dir: datadir / 'applications',
)

i18n.merge_file(
  input: metainfo_file,
  output: '@BASENAME@',
  type: 'xml',
  po_dir: meson.current_source_dir(),
  install: true,
  install_dir: datadir / 'metainfo',
)

i18n.gettext(
  meson.project_name(),
  args: [
    '--from-code=UTF-8',
    '--keyword=_',
    '--add-comments=translators',
    '--directory=@0@'.format(meson.project_source_root()),
    '--files-from=@0@'.format(meson.current_source_dir() / 'POTFILES'),
    '--msgid-bugs-address=https://github.com/virt-manager/virt-manager/issues',
    '--package-version=@0@'.format(meson.project_version()),
    '--sort-by-file',
  ],
)

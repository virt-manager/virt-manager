install_icons = []

subdir('16x16')
subdir('22x22')
subdir('24x24')
subdir('32x32')
subdir('48x48')
subdir('256x256')

foreach icon : install_icons
  if icon['cat'] == 'apps'
    icon_dir = datadir / 'icons' / 'hicolor' / icon['size'] / 'apps'
  else
    icon_dir = pkgdir / 'icons' / 'hicolor' / icon['size'] / icon['cat']
  endif
  install_data(
    icon['file'],
    install_dir: icon_dir,
  )
endforeach

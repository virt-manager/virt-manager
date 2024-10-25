scripts = [
  'make_bin_wrapper.py',
  'meson_dist.py',
]

foreach name : scripts
  sname = name.split('.')[0].underscorify()
  set_variable('@0@_prog'.format(sname), find_program(name))
endforeach

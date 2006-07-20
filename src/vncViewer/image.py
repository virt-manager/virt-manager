##
##  pyvnc2swf - image.py
##
##  $Id: image.py,v 1.9 2005/11/21 04:12:39 euske Exp $
##
##  Copyright (C) 2005 by Yusuke Shinyama (yusuke at cs . nyu . edu)
##  All Rights Reserved.
##
##  This is free software; you can redistribute it and/or modify
##  it under the terms of the GNU General Public License as published by
##  the Free Software Foundation; either version 2 of the License, or
##  (at your option) any later version.
##
##  This software is distributed in the hope that it will be useful,
##  but WITHOUT ANY WARRANTY; without even the implied warranty of
##  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
##  GNU General Public License for more details.
##
##  You should have received a copy of the GNU General Public License
##  along with this software; if not, write to the Free Software
##  Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307,
##  USA.
##

import sys
lowerbound = max
upperbound = min

#  format: 1: solid,
#          2: raw (uncompressed)
#          3: DefineBitLossless
#          4: SCREENVIDEOPACKET
IMG_SOLID = 1
IMG_RAW = 2
IMG_LOSSLESS = 3
IMG_VIDEOPACKET = 4

try:
  # try to pygame 1.6 or newer.
  import pygame
  pygame.init()
  def imgsize(img):
    return img.get_size()
  def create_image(w, h):
    return pygame.Surface((w, h), 0, 32)
  def create_image_from_string_rgb(w, h, data):
    return pygame.image.fromstring(data, (w, h), 'RGB')
  def create_image_from_string_rgbx(w, h, data):
    return pygame.image.fromstring(data, (w, h), 'RGBX')
  def create_image_from_string_xrgb(w, h, data):
    return pygame.image.fromstring(data[1:]+'x', (w, h), 'RGBX')
  def create_image_from_string_bgr_flipped(w, h, data):
    data = ''.join([ data[i+2]+data[i+1]+data[i] for i in xrange(0, len(data), 3) ])
    return pygame.transform.flip(pygame.image.fromstring(data, (w, h), 'RGB'), 0, 1)
  def crop_image(img, (x,y,w,h)):
    (wm,hm) = img.get_size()
    return img.subsurface((x,y,upperbound(wm-x,w),upperbound(hm-y,h)))
  def paste_image(dest, src, (x0, y0)):
    return dest.blit(src, (x0, y0))
  def save_image(img, fname):
    if not fname.endswith('.bmp'):
      print >>sys.stderr, 'Warning: this format not supported by pygame, raw rgb is used instead.'
    return pygame.image.save(img, fname)
  def convert_image_to_string_rgb_flipped(img):
    return pygame.image.tostring(img, 'RGB', 1)
  def convert_image_to_string_rgb(img):
    return pygame.image.tostring(img, 'RGB')
  def convert_image_to_string_xrgb(img):
    return pygame.image.tostring(img, 'ARGB')
  def solid_fill(dest, rect, color):
    return dest.fill(color, rect)
  def scale_image(img, scaling):
    # this might cause segmentation faults sometimes :(
    # In that case, use the following instead:
    #   (w,h) = img.get_size()
    #   return pygame.transform.scale(img, (int(w*scaling), int(h*scaling)))
    return pygame.transform.rotozoom(img, 0, scaling)

except ImportError:
  # use PIL instead
  pygame = None
  try:
    import Image
  except ImportError:
    print >>sys.stderr, 'Either Pygame or Python Imaging Library is required.'
    sys.exit(1)
  def imgsize(img):
    return img.size
  def create_image(w, h):
    return Image.new('RGB', (w, h))
  def create_image_from_string_rgb(w, h, data):
    return Image.fromstring('RGB', (w, h), data, 'raw', 'RGB')
  def create_image_from_string_rgbx(w, h, data):
    return Image.fromstring('RGB', (w, h), data, 'raw', 'RGBX')
  def create_image_from_string_xrgb(w, h, data):
    return Image.fromstring('RGB', (w, h), data[1:]+'x', 'raw', 'RGBX')
  def create_image_from_string_bgr_flipped(w, h, data):
    return Image.fromstring('RGB', (w, h), data, 'raw', 'BGR').transpose(Image.FLIP_TOP_BOTTOM)
  def crop_image(img, (x0,y0,w,h)):
    (wm,hm) = img.size
    return img.crop((x0, y0, upperbound(x0+w,wm), upperbound(y0+h,hm)))
  def paste_image(dest, src, (x0, y0)):
    return dest.paste(src, (x0, y0))
  def save_image(img, fname):
    return img.save(fname)
  def convert_image_to_string_rgb_flipped(img):
    return img.transpose(Image.FLIP_TOP_BOTTOM).tostring('raw', 'RGB')
  def convert_image_to_string_rgb(img):
    return img.tostring('raw', 'RGB')
  def convert_image_to_string_xrgb(img):
    return img.tostring('raw', 'XRGB')
  def solid_fill(dest, (x0,y0,w,h), color):
    return dest.paste(color, (x0, y0, x0+w, y0+h))
  def scale_image(img, scaling):
    img = img.copy()
    (w,h) = img.size
    img.thumbnail((int(w*scaling), int(h*scaling)), resample=1)
    return img


##
##  pyvnc2swf - rfb.py
##
##  $Id: rfb.py,v 1.25 2005/11/27 00:04:18 euske Exp $
##
##  Copyright (C) 2005 by Yusuke Shinyama (yusuke at cs . nyu . edu)
##  All Rights Reserved.
##
##  Adapted for use as a VNC widget in virtmanager:
##
##  Copyright (C) 2006 Red Hat Inc.
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


import sys, time, socket
from struct import pack, unpack
from crippled_des import DesCipher
stderr = sys.stderr
lowerbound = max


def byte2bit(s):
  return ''.join([ chr((ord(s[i>>3]) >> (7 - i&7)) & 1) for i in xrange(len(s)*8) ])


# Exceptions
class RFBError(Exception): pass
class RFBAuthError(RFBError): pass
class RFBProtocolError(RFBError): pass

ENCODING_RAW = 0
ENCODING_COPY_RECT = 1
ENCODING_RRE = 2
ENCODING_CORRE = 4
ENCODING_HEXTILE = 5
ENCODING_ZRLE = 16
ENCODING_DESKTOP_RESIZE = -223
ENCODING_CURSOR_POS = -232
ENCODING_RICH_CURSOR = -239
ENCODING_XCURSOR = -240

AUTH_INVALID = 0
AUTH_NONE = 1
AUTH_VNCAUTH = 2
AUTH_RA2 = 5
AUTH_RA2NE = 6
AUTH_TIGHT = 16
AUTH_ULTRA = 17
AUTH_TLS = 18

AUTH_VALID = [ AUTH_NONE, AUTH_VNCAUTH, AUTH_RA2, AUTH_RA2NE, AUTH_TIGHT, AUTH_ULTRA, AUTH_TLS ]
AUTH_SUPPORTED = [ AUTH_NONE, AUTH_VNCAUTH ]

##  RFBFrameBuffer
##
class RFBFrameBuffer:

  def init_screen(self, width, height, name):
    #print >>stderr, 'init_screen: %dx%d, name=%r' % (width, height, name)
    raise NotImplementedError

  def resize_screen(self, width, height):
    raise NotImplementedError

  def set_converter(self, convert_pixels, convert_color1):
    self.convert_pixels = convert_pixels
    self.convert_color1 = convert_color1
    return

  def process_pixels(self, x, y, width, height, data):
    #print >>stderr, 'process_pixels: %dx%d at (%d,%d)' % (width,height,x,y)
    raise NotImplementedError
  
  def process_solid(self, x, y, width, height, data):
    #print >>stderr, 'process_solid: %dx%d at (%d,%d), color=%r' % (width,height,x,y, color)
    raise NotImplementedError

  def update_screen(self, t):
    #print >>stderr, 'update_screen'
    raise NotImplementedError

  # data is given as ARGB
  def change_cursor(self, width, height, data):
    #print >>stderr, 'change_cursor'
    raise NotImplementedError

  def move_cursor(self, x, y):
    #print >>stderr, 'move_cursor'
    raise NotImplementedError
 
  def close(self):
    return
  

##  RFBProxy
##
class RFBProxy:
  "Abstract class of RFB clients."

  def __init__(self, fb=None, preferred_encoding=(ENCODING_RAW,ENCODING_HEXTILE), debug=0):
    self.fb = fb
    self.debug = debug
    self.preferred_encoding = preferred_encoding
    return

  FASTEST_FORMAT = (32, 8, 1, 1, 255, 255, 255, 24, 16, 8)
  def preferred_format(self, bitsperpixel, depth, bigendian, truecolour,
                       red_max, green_max, blue_max,
                       red_shift, green_shift, blue_shift):
    # should return 10-tuple (bitsperpixel, depth, bigendian, truecolour,
    #   red_max, green_max, blue_max, red_shift, green_shift, blue_shift)
    if self.fb:
      self.fb.set_converter(lambda data: data,
                            lambda data: unpack('BBBx', data))
    return self.FASTEST_FORMAT
  
  def send(self, s):
    "Send data s to the server."
    raise NotImplementedError

  def recv(self, n):
    "Receive n-bytes data from the server."
    raise NotImplementedError

  def recv_relay(self, n):
    "Same as recv() except the received data is also passed to self.relay.recv_framedata."
    return self.recv(n)

  def recv_byte_with_timeout(self):
    return self.recv_relay(1)

  def write(self, n):
    return
  
  def request_update(self):
    "Send a request to the server."
    raise NotImplementedError
  def finish_update(self):
    if self.fb:
      self.fb.update_screen(time.time())
    return
  
  def init(self):
    # recv: server protocol version
    server_version = self.recv(12)
    # send: client protocol version
    self.protocol_version = 3
    if server_version.startswith('RFB 003.007'):
      self.protocol_version = 7
    elif server_version.startswith('RFB 003.008'):
      self.protocol_version = 8
    self.send('RFB 003.%03d\x0a' % self.protocol_version)
    if self.debug:
      print >>stderr, 'protocol_version: 3.%d' % self.protocol_version

    self.auth_types = []

    if self.protocol_version == 3:
      # protocol 3.3 (or 3.6)
      # recv: server security
      (server_security,) = unpack('>L', self.recv(4))
      if self.debug:
        print >>stderr, 'server_security: %r' % server_security
      # server_security might be 0, 1 or 2.
      if int(server_security) == 0:
        (reason_length,) = unpack('>L', self.recv(4))
        reason = self.recv(reason_length)
        raise RFBAuthError('Auth Error: %s' % reason)
      elif int(server_security) in AUTH_VALID:
        self.auth_types = [ server_security ]
      else:
        raise "illegal auth type %d" % server_security
    elif self.protocol_version >= 7:
      (nsecurities,) = unpack('>B', self.recv(1))
      server_securities = self.recv(nsecurities)
      if self.debug:
        print >>stderr, 'server_securities: %r' % server_securities
      for type in server_securities:
        if ord(type) in AUTH_SUPPORTED:
          self.auth_types.append(ord(type))

      if len(self.auth_types) == 0:
        raise "no valid auth types in " + str(server_securities)

    return self.auth_types

  def getpass(self):
    raise NotImplementedError


  def auth(self):

    # vnc challange & response auth
    def crauth():
      p = self.getpass()
      if not p:
        raise RFBError('Auth cancelled')
      # from pyvncviewer
      des = DesCipher((p+'\x00'*8)[:8])
      challange = self.recv(16)
      if self.debug:
        print >>stderr, 'challange: %r' % challange
      response = des.encrypt(challange[:8]) + des.encrypt(challange[8:])
      if self.debug:
        print >>stderr, 'response: %r' % response
      self.send(response)
      # recv: security result
      (result,) = unpack('>L', self.recv(4))
      return result

    server_result = 0
    if self.protocol_version == 3:
      if AUTH_NONE in self.auth_types:
        server_result = 0
      elif AUTH_VNCAUTH in self.auth_types:
        server_result = crauth()
    elif self.protocol_version >= 7:
      if AUTH_NONE in self.auth_types:
        self.send('\x01')
        if self.protocol_version == 8:
          # Protocol 3.8: must recv security result
          (server_result,) = unpack('>L', self.recv(4))
        else:
          server_result = 0
      elif AUTH_VNCAUTH in self.auth_types:
        self.send('\x02')
        server_result = crauth()
      else:
        raise "no supported auth types"
    # result returned.
    if self.debug:
      print >>stderr, 'server_result: %r' % server_result
    if server_result != 0:
      # auth failed.
      if self.protocol_version != 3:
        (reason_length,) = unpack('>L', self.recv(4))
        reason = self.recv(reason_length)
      else:
        reason = server_result
      raise RFBAuthError('Auth Error: %s' % reason)

  def start(self, shared=True):
    if shared:
      self.send('\x01')
    else:
      self.send('\x00')

    # server info.
    server_init = self.recv(24)
    (width, height, pixelformat, namelen) = unpack('>HH16sL', server_init)
    self.name = self.recv(namelen)
    (bitsperpixel, depth, bigendian, truecolour,
     red_max, green_max, blue_max,
     red_shift, green_shift, blue_shift) = unpack('>BBBBHHHBBBxxx', pixelformat)
    if self.debug:
      print >>stderr, 'Server Encoding:'
      print >>stderr, ' width=%d, height=%d, name=%r' % (width, height, self.name)
      print >>stderr, ' pixelformat=', (bitsperpixel, depth, bigendian, truecolour)
      print >>stderr, ' rgbmax=', (red_max, green_max, blue_max)
      print >>stderr, ' rgbshift=', (red_shift, green_shift, blue_shift)
    # setformat
    self.send('\x00\x00\x00\x00')
    # 32bit, 8bit-depth, big-endian(RGBX), truecolour, 255max
    (bitsperpixel, depth, bigendian, truecolour,
     red_max, green_max, blue_max,
     red_shift, green_shift, blue_shift) = self.preferred_format(bitsperpixel, depth, bigendian, truecolour,
                                                                 red_max, green_max, blue_max,
                                                                 red_shift, green_shift, blue_shift)
    self.bytesperpixel = bitsperpixel/8
    pixelformat = pack('>BBBBHHHBBBxxx', bitsperpixel, depth, bigendian, truecolour,
                       red_max, green_max, blue_max,
                       red_shift, green_shift, blue_shift)
    self.send(pixelformat)
    self.write(pack('>HH16sL', width, height, pixelformat, namelen))
    self.write(self.name)
    if self.fb:
      self.clipping = self.fb.init_screen(width, height, self.name)
    else:
      self.clipping = (0,0, width, height)
    self.send('\x02\x00' + pack('>H', len(self.preferred_encoding)))
    for e in self.preferred_encoding:
      self.send(pack('>l', e))
    return self
  
  def loop1(self):
    self.request_update()
    c = self.recv_byte_with_timeout()
    if c == '':
      return False
    elif c == None:
      # timeout
      pass
    elif c == '\x00':
      (nrects,) = unpack('>xH', self.recv_relay(3))
      if self.debug:
        print >>stderr, 'FrameBufferUpdate: nrects=%d' % nrects
      for rectindex in xrange(nrects):
        (x0, y0, width, height, t) = unpack('>HHHHl', self.recv_relay(12))
        if self.debug:
          print >>stderr, ' %d: %d x %d at (%d,%d), type=%d' % (rectindex, width, height, x0, y0, t)

        if t == ENCODING_RAW:
          l = width*height*self.bytesperpixel
          data = self.recv_relay(l)
          if self.debug:
            print >>stderr, ' RawEncoding: len=%d, received=%d' % (l, len(data))
          if self.fb:
            self.fb.process_pixels(x0, y0, width, height, data)

        elif t == ENCODING_COPY_RECT:
          raise RFBProtocolError('unsupported: CopyRectEncoding')

        elif t == ENCODING_RRE:
          (nsubrects,) = unpack('>L', self.recv_relay(4))
          bgcolor = self.recv_relay(self.bytesperpixel)
          if self.debug:
            print >>stderr, ' RREEncoding: subrects=%d, bgcolor=%r' % (nsubrects, bgcolor)
          if self.fb:
            self.fb.process_solid(x0, y0, width, height, bgcolor)
          for i in xrange(nsubrects):
            fgcolor = self.recv_relay(self.bytesperpixel)
            (x,y,w,h) = unpack('>HHHH', self.recv_relay(8))
            if self.fb:
              self.fb.process_solid(x0+x, y0+y, w, h, fgcolor)
            if 2 <= self.debug:
              print >>stderr, ' RREEncoding: ', (x,y,w,h,fgcolor)

        elif t == ENCODING_CORRE:
          (nsubrects,) = unpack('>L', self.recv_relay(4))
          bgcolor = self.recv_relay(self.bytesperpixel)
          if self.debug:
            print >>stderr, ' CoRREEncoding: subrects=%d, bgcolor=%r' % (nsubrects, bgcolor)
          if self.fb:
            self.fb.process_solid(x0, y0, width, height, bgcolor)
          for i in xrange(nsubrects):
            fgcolor = self.recv_relay(self.bytesperpixel)
            (x,y,w,h) = unpack('>BBBB', self.recv_relay(4))
            if self.fb:
              self.fb.process_solid(x0+x, y0+y, w, h, fgcolor)
            if 2 <= self.debug:
              print >>stderr, ' CoRREEncoding: ', (x,y,w,h,fgcolor)

        elif t == ENCODING_HEXTILE:
          if self.debug:
            print >>stderr, ' HextileEncoding'
          (fgcolor, bgcolor) = (None, None)
          for y in xrange(0, height, 16):
            for x in xrange(0, width, 16):
              w = min(width-x, 16)
              h = min(height-y, 16)
              c = ord(self.recv_relay(1))
              assert c < 32
              # Raw
              if c & 1:
                l = w*h*self.bytesperpixel
                data = self.recv_relay(l)
                if self.fb:
                  self.fb.process_pixels(x0+x, y0+y, w, h, data)
                if 2 <= self.debug:
                  print >>stderr, '  Raw:', l
                continue
              if c & 2:
                bgcolor = self.recv_relay(self.bytesperpixel)
              if c & 4:
                fgcolor = self.recv_relay(self.bytesperpixel)
              if self.fb:
                self.fb.process_solid(x0+x, y0+y, w, h, bgcolor)
              # Solid
              if not c & 8:
                if 2 <= self.debug:
                  print >>stderr, '  Solid:', repr(bgcolor)
                continue
              nsubrects = ord(self.recv_relay(1))
              # SubrectsColoured
              if c & 16:
                if 2 <= self.debug:
                  print >>stderr, '  SubrectsColoured:', nsubrects, repr(bgcolor)
                for i in xrange(nsubrects):
                  color = self.recv_relay(self.bytesperpixel)
                  (xy,wh) = unpack('>BB', self.recv_relay(2))
                  if self.fb:
                    self.fb.process_solid(x0+x+(xy>>4), y0+y+(xy&15), (wh>>4)+1, (wh&15)+1, color)
                  if 3 <= self.debug:
                    print >>stderr, '   ', repr(color), (xy,wh)
              # NoSubrectsColoured
              else:
                if 2 <= self.debug:
                  print >>stderr, '  NoSubrectsColoured:', nsubrects, repr(bgcolor)
                for i in xrange(nsubrects):
                  (xy,wh) = unpack('>BB', self.recv_relay(2))
                  if self.fb:
                    self.fb.process_solid(x0+x+(xy>>4), y0+y+(xy&15), (wh>>4)+1, (wh&15)+1, fgcolor)
                  if 3 <= self.debug:
                    print >>stderr, '  ', (xy,wh)

        elif t == ENCODING_ZRLE:
          raise RFBProtocolError('unsupported: ZRLEEncoding')

        elif t == ENCODING_DESKTOP_RESIZE:
          self.clipping = self.fb.resize_screen(width, height)

        elif t == ENCODING_RICH_CURSOR:
          if width and height:
            rowbytes = (width + 7) / 8;
            # Cursor image RGB
            data = self.recv_relay(width * height * self.bytesperpixel)
            # Cursor mask -> 1 bit/pixel (1 -> image; 0 -> transparent)
            mask = self.recv_relay(rowbytes * height)
            # Set the alpha channel with maskData where bit=1 -> alpha = 255, bit=0 -> alpha=255
            if self.debug:
              print >>stderr, 'RichCursor: %dx%d at %d,%d' % (width,height,x0,y0)
            if self.fb:
              data = self.fb.convert_pixels(data)
              mask = ''.join([ byte2bit(mask[p:p+rowbytes]) for p in xrange(0, height*rowbytes, rowbytes) ])
              def conv1(i):
                if mask[i/4] == '\x01':
                  return '\xff'+data[i]+data[i+1]+data[i+2]
                else:
                  return '\x00\x00\x00\x00'
              data = ''.join([ conv1(i) for i in xrange(0, len(data), 4) ])
              self.fb.change_cursor(width, height, x0, y0, data)

        elif t == ENCODING_XCURSOR:
          if width and height:
            rowbytes = (width + 7) / 8;
            # Foreground RGB
            fgcolor = self.recv_relay(3)
            # Background RGB
            bgcolor = self.recv_relay(3)
            # Cursor Data -> 1 bit/pixel
            data = self.recv_relay(rowbytes * height)
            # Cursor Mask -> 1 bit/pixel
            mask = self.recv_relay(rowbytes * height)
            # Create the image from cursordata and maskdata.
            print >>stderr, 'XCursor: %dx%d at %d,%d' % (width,height,x0,y0)
            if self.fb:
              data = byte2bit(data)
              mask = byte2bit(mask)
              def conv1(i):
                if mask[i] == '\x01':
                  if data[i] == '\x01':
                    return '\xff'+fgcolor
                  else:
                    return '\xff'+bgcolor
                else:
                  return '\x00\x00\x00\x00'
              data = ''.join([ conv1(i) for i in xrange(len(data)) ])
              self.fb.change_cursor(width, height, x0, y0, data)

        elif t == ENCODING_CURSOR_POS:
          if self.debug:
            print >>stderr, 'CursorPos: %d,%d' % (x0,y0)
          if self.fb:
            self.fb.move_cursor(x0, y0)
        else:
          raise RFBProtocolError('Illegal encoding: 0x%02x' % t)
      self.finish_update()
    elif c == '\x01':
      (first, ncolours) = unpack('>xHH', self.recv_relay(11))
      if self.debug:
        print >>stderr, 'SetColourMapEntries: first=%d, ncolours=%d' % (first, ncolours)
      for i in ncolours:
        self.recv_relay(6)

    elif c == '\x02':
      if self.debug:
        print >>stderr, 'Bell'

    elif c == '\x03':
      (length, ) = unpack('>3xL', self.recv_relay(7))
      data = self.recv_relay(length)
      if self.debug:
        print >>stderr, 'ServerCutText: %r' % data

    else:
      raise RFBProtocolError('Unsupported msg: %d' % ord(c))

    return True

  def loop(self):
    while self.loop1():
      pass
    self.finish_update()
    return self

  def close(self):
    if self.fb:
      self.fb.close()
    return


##  RFBNetworkClient
##
class RFBNetworkClient(RFBProxy):
  
  def __init__(self, host, port, fb=None, pwdfile=None,
               preferred_encoding=(ENCODING_RAW,ENCODING_HEXTILE), debug=0):
    RFBProxy.__init__(self, fb=fb, preferred_encoding=preferred_encoding, debug=debug)
    self.host = host
    self.port = port
    self.pwdfile = pwdfile
    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    return

  def init(self):
    self.sock.connect((self.host, self.port))
    return RFBProxy.init(self)

  def recv(self, n):
    # MS-Windows doesn't have MSG_WAITALL, so we emulate it.
    buf = ''
    while n:
      x = self.sock.recv(n)
      if not x: break
      buf += x
      n -= len(x)
    return buf

  def recv_byte_with_timeout(self):
    self.sock.settimeout(0.05)
    try:
      c = self.recv_relay(1)
    except socket.timeout:
      c = None
    self.sock.settimeout(None)
    return c

  def send(self, s):
    return self.sock.send(s)
    
  def getpass(self):
    import getpass
    if self.pwdfile:
      fp = file(self.pwdfile)
      s = fp.read().rstrip()
      fp.close()
      return s
    return getpass.getpass('Password for %s:%d: ' % (self.host, self.port))

  def request_update(self):
    if self.debug:
      print >>stderr, 'FrameBufferUpdateRequest'
    self.send('\x03\x01' + pack('>HHHH', *self.clipping))
    return

  def close(self):
    RFBProxy.close(self)
    self.sock.close()
    return



#!/usr/bin/env python
##
##  pyvnc2swf - rfb.py
##
##  $Id: rfb.py,v 1.25 2005/11/27 00:04:18 euske Exp $
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


import sys, time, socket
from struct import pack, unpack
from crippled_des import DesCipher
from image import IMG_SOLID, IMG_RAW
stderr = sys.stderr
lowerbound = max


def byte2bit(s):
  return ''.join([ chr((ord(s[i>>3]) >> (7 - i&7)) & 1) for i in xrange(len(s)*8) ])


# Exceptions
class RFBError(Exception): pass
class RFBAuthError(RFBError): pass
class RFBProtocolError(RFBError): pass



##  RFBFrameBuffer
##
class RFBFrameBuffer:

  def init_screen(self, width, height, name):
    #print >>stderr, 'init_screen: %dx%d, name=%r' % (width, height, name)
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

  def __init__(self, fb=None, preferred_encoding=(5,0), debug=0):
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
    return self

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
      # protocol 3.3 (or 3.6)
      # recv: server security
      (server_security,) = unpack('>L', self.recv(4))
      if self.debug:
        print >>stderr, 'server_security: %r' % server_security
      # server_security might be 0, 1 or 2.
      if server_security == 0:
        (reason_length,) = unpack('>L', self.recv(4))
        reason = self.recv(reason_length)
        raise RFBAuthError('Auth Error: %s' % reason)
      elif server_security == 1:
        pass
      else:
        server_result = crauth()
    else:
      # protocol 3.7 or 3.8
      # recv: multiple server securities
      (nsecurities,) = unpack('>B', self.recv(1))
      server_securities = self.recv(nsecurities)
      if self.debug:
        print >>stderr, 'server_securities: %r' % server_securities
      # must include None or VNCAuth
      if '\x01' in server_securities:
        # None
        self.send('\x01')
        if self.protocol_version == 8:
          # Protocol 3.8: must recv security result
          (server_result,) = unpack('>L', self.recv(4))
        else:
          server_result = 0
      elif '\x02' in server_securities:
        # VNCAuth
        self.send('\x02')
        server_result = crauth()
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
    # negotiation ok.
    # send: always shared.
    self.send('\x01')
    return self

  def start(self):
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
        # RawEncoding
        if t == 0:
          l = width*height*self.bytesperpixel
          data = self.recv_relay(l)
          if self.debug:
            print >>stderr, ' RawEncoding: len=%d, received=%d' % (l, len(data))
          if self.fb:
            self.fb.process_pixels(x0, y0, width, height, data)
        # CopyRectEncoding
        elif t == 1:
          raise RFBProtocolError('unsupported: CopyRectEncoding')
        # RREEncoding
        elif t == 2:
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
        # CoRREEncoding
        elif t == 4:
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
        # HextileEncoding
        elif t == 5:
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
        # ZRLEEncoding
        elif t == 16:
          raise RFBProtocolError('unsupported: ZRLEEncoding')
        # RichCursor
        elif t == -239:
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
        # XCursor
        elif t == -240:
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
        # CursorPos -> only change the cursor position
        elif t == -232:
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
               preferred_encoding=(0,5), debug=0):
    RFBProxy.__init__(self, fb=fb, preferred_encoding=preferred_encoding, debug=debug)
    self.host = host
    self.port = port
    self.pwdfile = pwdfile
    self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    return

  def init(self):
    self.sock.connect((self.host, self.port))
    x = RFBProxy.init(self)
    print >>stderr, 'Connected: %s:%d, protocol_version=3.%d, preferred_encoding=%s' % \
          (self.host, self.port, self.protocol_version, self.preferred_encoding)
    return x

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


##  RFBNetworkClientForRecording (vncrec equivalent)
##
class RFBNetworkClientForRecording(RFBNetworkClient):
  
  def __init__(self, host, port, fname, pwdfile=None,
               preferred_encoding=(5,0), debug=0):
    RFBNetworkClient.__init__(self, host, port, fb=None, pwdfile=pwdfile,
                              preferred_encoding=preferred_encoding, debug=debug)
    print >>stderr, 'Creating vncrec: %r: vncLog0.0' % fname
    self.fp = file(fname, 'wb')
    self.write('vncLog0.0')
    # disguise data (security=none)
    self.write('RFB 003.003\x0a')
    self.write('\x00\x00\x00\x01')
    self.updated = True
    return

  def write(self, x):
    self.fp.write(x)
    return

  def request_update(self):
    if self.updated:
      self.updated = False
      t = time.time()
      self.write(pack('>LL', int(t), (t-int(t))*1000000))
      RFBNetworkClient.request_update(self)
    return
  
  def finish_update(self):
    self.updated = True
    return
  
  def recv_relay(self, n):
    data = self.recv(n)
    self.write(data)
    return data

  def close(self):
    RFBNetworkClient.close(self)
    self.fp.close()
    return


##  RFBFileParser
##
class RFBFileParser(RFBProxy):
  
  def __init__(self, fname, fb=None, debug=0):
    RFBProxy.__init__(self, fb=fb, debug=debug)
    if self.fb:
      self.fb.change_format = False
    self.fp = file(fname, 'rb')
    self.fname = fname
    return

  def preferred_format(self, bitsperpixel, depth, bigendian, truecolour,
                       red_max, green_max, blue_max,
                       red_shift, green_shift, blue_shift):
    if (bitsperpixel, depth, bigendian, truecolour,
        red_max, green_max, blue_max,
        red_shift, green_shift, blue_shift) == self.FASTEST_FORMAT:
      return RFBProxy.preferred_format(self, bitsperpixel, depth, bigendian, truecolour,
                                       red_max, green_max, blue_max,
                                       red_shift, green_shift, blue_shift)
    elif self.fb:
      if bigendian:
        endian = '>'
      else:
        endian = '<'
      try:
        length = {8:'B', 16:'H', 32:'L'}[bitsperpixel]
      except KeyError:
        raise 'invalid bitsperpixel: %d' % bitsperpixel
      unpackstr = endian + length
      nbytes = bitsperpixel / 8
      bits = {1:1, 3:2, 7:3, 15:4, 31:5, 63:6, 127:7, 255:8}
      try:
        e = 'lambda p: (((p>>%d)&%d)<<%d, ((p>>%d)&%d)<<%d, ((p>>%d)&%d)<<%d)' % \
            (red_shift, red_max, 8-bits[red_max],
             green_shift, green_max, 8-bits[green_max],
             blue_shift, blue_max, 8-bits[blue_max])
      except KeyError:
        raise 'invalid {red,green,blue}_max: %d, %d or %d' % (red_max, green_max, blue_max)
      getrgb = eval(e)
      unpack_pixels = eval('lambda data: unpack("%s%%d%s" %% (len(data)/%d), data)' % (endian, length, nbytes))
      unpack_color1 = eval('lambda data: unpack("%s", data)' % unpackstr)
      self.fb.set_converter(lambda data: ''.join([ pack('>BBB', *getrgb(p)) for p in unpack_pixels(data) ]),
                            lambda data: getrgb(unpack_color1(data)[0]))
    return (bitsperpixel, depth, bigendian, truecolour,
            red_max, green_max, blue_max,
            red_shift, green_shift, blue_shift)

  def seek(self, pos):
    self.fp.seek(pos)
    return
  def tell(self):
    return self.fp.tell()

  def init(self):
    self.curtime = 0
    version = self.fp.read(9)
    print >>stderr, 'Reading vncrec file: %s, version=%r...' % (self.fname, version)
    if version != 'vncLog0.0':
      raise RFBProtocolError('Unsupported vncrec version: %r' % version)
    return RFBProxy.init(self)
  
  def recv(self, n):
    x = self.fp.read(n)
    if len(x) != n:
      raise EOFError
    return x

  def send(self, s):
    return

  def auth(self):
    if self.protocol_version == 3:
      # protocol 3.3
      # recv: server security
      (server_security,) = unpack('>L', self.recv(4))
      if self.debug:
        print >>stderr, 'server_security=%r' % server_security
      if server_security == 2:
        # skip challenge+result (dummy)
        self.recv(20)
    else:
      RFBProxy.auth(self)
    return self

  def request_update(self):
    (sec, usec) = unpack('>LL', self.recv(8))
    self.curtime = sec+usec/1000000.0
    return
  
  def finish_update(self):
    if self.fb:
      self.fb.update_screen(self.curtime) # use the file time instead
    return

  def loop(self, endpos=0):
    try:
      while self.loop1():
        if endpos and endpos <= self.tell(): break
    except EOFError:
      self.finish_update()
    return self

  def close(self):
    RFBProxy.close(self)
    self.fp.close()
    return


##  RFBConverter
##
class RFBConverter(RFBFrameBuffer):

  def __init__(self, info, debug=0):
    self.debug = debug
    self.info = info
    return

  def init_screen(self, width, height, name):
    print >>stderr, 'VNC Screen: size=%dx%d, name=%r' % (width, height, name)
    self.info.set_defaults(width, height)
    self.images = []
    self.cursor_image = None
    self.cursor_pos = None
    self.t0 = 0
    return self.info.clipping

  def process_pixels(self, x, y, width, height, data):
    self.images.append( ((x, y), (width, height, (IMG_RAW, self.convert_pixels(data)))) )
    return
  
  def process_solid(self, x, y, width, height, data):
    self.images.append( ((x, y), (width, height, (IMG_SOLID, self.convert_color1(data)))) ) 
    return

  def move_cursor(self, x, y):
    self.cursor_pos = (x, y)
    return

  def change_cursor(self, width, height, dx, dy, data):
    if width and height:
      self.cursor_image = (width, height, dx, dy, data)
    return

  def calc_frames(self, t):
    if not self.t0:
      self.t0 = t
    return int((t - self.t0) * self.info.framerate)+1


##  RFBMovieConverter
##
class RFBMovieConverter(RFBConverter):

  def __init__(self, movie, debug=0):
    RFBConverter.__init__(self, movie.info, debug)
    self.movie = movie
    self.frameinfo = []
    return

  def process_pixels(self, x, y, width, height, data):
    if self.processing:
      RFBConverter.process_pixels(self, x, y, width, height, data)
    return
  
  def process_solid(self, x, y, width, height, data):
    if self.processing:
      RFBConverter.process_solid(self, x, y, width, height, data)
    return

  def update_screen(self, t):
    if not self.processing:
      frames = RFBConverter.calc_frames(self, t)
      done = False
      while len(self.frameinfo) < frames:
        if done:
          self.frameinfo.append((self.beginpos, -1))
        else:
          endpos = self.rfbparser.tell()
          self.frameinfo.append((self.beginpos, endpos))
          if self.debug:
            print >>stderr, 'scan:', self.beginpos, endpos
          self.beginpos = endpos
          done = True
    return

  def open(self, fname, debug=0):
    self.processing = False
    self.rfbparser = RFBFileParser(fname, self, debug)
    self.rfbparser.init().auth().start()
    self.beginpos = self.rfbparser.tell()
    self.rfbparser.loop()
    return

  def parse_frame(self, i):
    (pos, endpos) = self.frameinfo[i]
    if self.debug:
      print >>stderr, 'seek:', i, pos, endpos
    self.rfbparser.seek(pos)
    self.images = []
    self.processing = True
    self.cursor_image = None
    self.cursor_pos = None
    self.rfbparser.loop(endpos)
    return (self.images, [], (self.cursor_image, self.cursor_pos))


##  RFBStreamConverter
##
class RFBStreamConverter(RFBConverter):
  
  def __init__(self, info, stream, debug=0):
    RFBConverter.__init__(self, info, debug)
    self.stream = stream
    return
  
  def init_screen(self, width, height, name):
    clipping = RFBConverter.init_screen(self, width, height, name)
    self.stream.open()
    self.nframes = 0
    return clipping
  
  def update_screen(self, t):
    frames = RFBConverter.calc_frames(self, t)
    if self.nframes < frames:
      # First we should create the frames up to now
      while self.nframes < frames-1:
        self.stream.next_frame()
        self.nframes += 1
      # And only after that we should paint the frame with the updates
      self.stream.paint_frame((self.images, [], (self.cursor_image, self.cursor_pos)))
      self.images = []
      self.cursor_image = None
      self.cursor_pos = None
      self.stream.next_frame()
      self.nframes += 1
    return
  
  def close(self):
    self.stream.close()
    return

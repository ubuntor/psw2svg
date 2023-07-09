# partially based on libwps

import struct
import sys
import drawsvg # https://pypi.org/project/drawsvg/

COLORS = [
	(0,0,0), (132,130,132), (198,195,198), (255,255,255),
	(255,0,0), (0,255,0), (0,0,255), (0,255,255),
	(255,0,255), (0,255,255), (132,0,0), (0,130,0),
	(0,0,132), (0,130,132),	(132,0,132), (132, 130, 0)
]

class Buffer:
    def __init__(self, b):
        self.raw = b
        self.fp = 0
    def read(self, n):
        ret = self.raw[self.fp : self.fp + n]
        self.fp += n
        return ret
    def readall(self):
        ret = self.raw[self.fp :]
        self.fp = len(self.raw)
        return ret
    def peek(self, n):
        ret = self.raw[self.fp : self.fp + n]
        return ret
    def eof(self):
        return self.fp >= len(self.raw)
    def peek_u8(self):
        return self.peek(1)[0]
    def read_u8(self):
        return self.read(1)[0]
    def read_u16(self):
        return struct.unpack("<H", self.read(2))[0]

class CompressedIntBuffer:
    def __init__(self, b):
        # blargh
        self.bits = ""
        for i in b:
            self.bits += f"{i:08b}"[::-1]
        self.fp = 0

    def _read_s(self, n):
        ret = int(self.bits[self.fp : self.fp + n][::-1], 2)
        if ret & (1 << (n-1)):
            ret -= 1 << n
        self.fp += n
        return ret

    def read_compressed_int(self):
        # first 5 bits: -0xf ~ 0xf
        x = self._read_s(5)
        if x != -0x10:
            return x
        # next 6 bits: -0x2e ~ -0x10, 0x10 ~ 0x2f
        x = self._read_s(6)
        if x >= 0:
            x += 16
        else:
            x -= 15
        if x != -0x2f:
            return x
        # next 8 bits: -0x7f ~ 0x7f (no shifting?)
        x = self._read_s(8)
        if x != -0x80:
            return x
        # next 16 bits: -0x7fff ~ 0x7fff (no shifting?)
        x = self._read_s(16)
        if x != -0x8000:
            return x
        print('ERROR: bad int encoding (exceeded 16 bits)')
        sys.exit(1)

def format_color(x):
    return f'rgb({x[0]}, {x[1]}, {x[2]})'

if __name__ == '__main__':
    if len(sys.argv) <= 2:
        print(f'usage: {sys.argv[0]} [input psw/pwi file] [output svg file]')
        sys.exit(1)
    with open(sys.argv[1],'rb') as f:
        b = Buffer(f.read())
    if b.read(10) != bytes.fromhex('7b5c7077691500000101'):
        print('ERROR: not a psw/pwi file? (bad header)')
        sys.exit(1)

    svg = drawsvg.Drawing(100, 100)

    bounds = [100, 100]
    version = b.read_u16()
    b.read_u16() # TODO: ???
    text_cursor = [0, 0]
    drawing_origin = (0, 0)
    drawing_size = (0, 0)
    # what on earth is up with these coordinate systems???
    # shape coordinates use +y=up, drawing origins use +y=up (but +lines=down)
    while not b.eof():
        _type = b.read_u16()
        _id = b.read_u16()
        length = b.read_u16()
        if _type != 85:
            length *= 4
        data = Buffer(b.read(length))
        #print(_type, hex(_id))
        if _type == 131: # drawing info
            # TODO: instead of storing drawing state, lookup the shapes by the ids
            data.read(8) # TODO: ???
            line = data.read_u16()
            data.read(2) # TODO: ???
            drawing_origin = (data.read_u16(), (line+1)*72-data.read_u16()) # TODO: line height?
            drawing_size = (data.read_u16(), data.read_u16())
            bounds[0] = max(bounds[0], drawing_origin[0]+drawing_size[0])
            bounds[1] = max(bounds[1], drawing_origin[1]+drawing_size[1])
            svg.append(drawsvg.Rectangle(*drawing_origin, *drawing_size, fill='none', stroke='red', stroke_width=1)) # TODO: delet this
            svg.append(drawsvg.Text(f'{drawing_origin}, {drawing_size}, {drawing_origin[1]-line*72}, {line}', font_size=20, font_family='sansserif', x=drawing_origin[0], y=drawing_origin[1])) # TODO: delet this
        elif _type == 103: # polyline
            data.read(3) # TODO: ???
            color = data.read_u8()
            stroke = COLORS[color & 0xf]
            fill = COLORS[color >> 4]
            width = data.read_u8()
            is_filled = bool(data.read_u8())
            data.read(6) # TODO: ???
            offset = (drawing_origin[0]+data.read_u16(), drawing_origin[1]+drawing_size[1]-data.read_u16())
            size = (data.read_u16(), data.read_u16())
            transform = data.read(20)
            if transform != bytes.fromhex('0000010000000100000000000000000000000000'):
                print('WARNING: polyline transform unimplemented')
            if data.peek_u8() >= 0xf0:
                # -- -- [f2 f2] [num_points num_points] [base_x base_x] [base_y base_y]
                data.read_u16()
                f2 = data.read_u16()
                num_points = data.read_u16()
                x, y = offset[0]+data.read_u16(), offset[1]-data.read_u16()
            else:
                # num_points f2 base_x base_y
                num_points = data.read_u8()
                f2 = data.read_u8()
                x, y = offset[0]+data.read_u8(), offset[1]-data.read_u8()
            coords = [x, y]
            data = CompressedIntBuffer(data.readall())
            for _ in range(num_points-1):
                x += data.read_compressed_int()
                y -= data.read_compressed_int()
                coords += [x,y]
            if is_filled:
                svg.append(drawsvg.Lines(*coords, fill=format_color(fill), stroke=format_color(stroke), stroke_width=width, close='true'))
            else:
                svg.append(drawsvg.Lines(*coords, fill='none', stroke=format_color(stroke), stroke_width=width))
        elif _type == 67: # inline polyline
            print('WARNING: inline polyline not fully implemented')
            data.read(4) # TODO: ???
            width = data.read_u16()
            data.read(4) # TODO: ???
            if data.peek_u8() >= 0xf0:
                # -- -- [f2 f2] [num_points num_points] [base_x base_x] [base_y base_y]
                data.read_u16()
                f2 = data.read_u16()
                num_points = data.read_u16()
                x, y = text_cursor[0]+data.read_u16(), text_cursor[1]+data.read_u16()
            else:
                # num_points f2 base_x base_y
                num_points = data.read_u8()
                f2 = data.read_u8()
                x, y = text_cursor[0]+data.read_u8(), text_cursor[1]+data.read_u8()
            coords = [x, y]
            data = CompressedIntBuffer(data.readall())
            for _ in range(num_points-1):
                x += data.read_compressed_int()
                y -= data.read_compressed_int()
                coords += [x,y]
            svg.append(drawsvg.Lines(*coords, fill='none', stroke=format_color(COLORS[0]), stroke_width=4)) # ???
            text_cursor[0] += width # TODO: ???
        elif _type == 65: # paragraph?
            pass
        elif _type == 66: # paragraph?
            text_cursor[0] = 0
            text_cursor[1] += 50 # TODO: ???
        elif _type == 102:
            print('WARNING: group unimplemented!')
        elif _type == 104:
            print('WARNING: rectangle unimplemented!')
        elif _type == 105:
            print('WARNING: circle unimplemented!')
        elif _type == 106:
            print('WARNING: line unimplemented!')
        elif _type == 107:
            print('WARNING: triangle unimplemented!')

    svg.width = bounds[0]
    svg.height = bounds[1]
    svg.view_box = (0, 0, bounds[0], bounds[1])
    svg.save_svg(sys.argv[2])

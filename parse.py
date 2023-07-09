# partially based on libwps

import struct
import sys
import drawsvg # https://pypi.org/project/drawsvg/

COLORS = [
	(0,0,0), (132,130,132), (198,195,198), (255,255,255),
	(255,0,0), (0,255,0), (0,0,255), (0,255,255),
	(255,0,255), (0,255,255), (132,0,0), (0,130,0),
	(0,0,132), (0,130,132),	(132,0,132), (132,130,0)
]

PARAGRAPH_COMMAND_LEN = {
    0xc1:1,
    0xc2:2,
    0xc3:2,
    0xc4:1,
    0xc5:2,
    0xe5:2,
    0xe6:2,
    0xe7:2,
    0xe8:2,
    0xe9:1,
    0xea:1,
    0xeb:1,
    0xec:1,
    0xef:3
}

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
    def read_s16(self):
        return struct.unpack("<h", self.read(2))[0]
    def read_u32(self):
        return struct.unpack("<I", self.read(4))[0]

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

def decode_polyline(data, offset):
    if data.peek_u8() >= 0xf0:
        # -- -- [num_bytes num_bytes] [num_points num_points] [base_x base_x] [base_y base_y]
        data.read(2)
        num_bytes = data.read_u16()-10
        num_points = data.read_u16()
        x, y = offset[0]+data.read_u16(), offset[1]-data.read_u16()
    else:
        # num_points num_bytes base_x base_y
        num_points = data.read_u8()
        num_bytes = data.read_u8()-4
        x, y = offset[0]+data.read_u8(), offset[1]-data.read_u8()
    coords = [x, y]
    compressed_data = CompressedIntBuffer(data.read(num_bytes))
    for _ in range(num_points-1):
        x += compressed_data.read_compressed_int()
        y -= compressed_data.read_compressed_int()
        coords += [x,y]
    return coords

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
    chunks = {}
    bounds = [100, 100]
    version = b.read_u16()
    print(f'version {version}')
    if version != 6:
        print(f'WARNING: unsupported version, might not work')
    b.read_u16()

    while not b.eof():
        _type = b.read_u16()
        _id = b.read_u16()
        length = b.read_u16()
        if _type != 85:
            length *= 4
        data = Buffer(b.read(length))
        chunks[_id] = (_type, data)

    # TODO: what even are units??? pixels? pt?

    # parse paragraphs (id 8)
    if 8 not in chunks:
        print('WARNING: no paragraphs?')
    else:
        _, data = chunks[8]
        num_paragraphs = data.read_u32()
        data.read_u32() # total lines?
        data.read_u32() # total chars?
        data.read_u32() # ???
        data.read_u32() # 0?
        data.read_u32() # 0?
        paragraphs = []
        for _ in range(num_paragraphs):
            num_lines = data.read_u16()
            data.read(2)
            paragraph_id = data.read_u16()
            data.read(2)
            paragraphs.append((paragraph_id, num_lines))
        cursor = [0, 0]
        print('paragraphs:', paragraphs)
        for paragraph_id, num_lines in paragraphs:
            cursor[1] += 72*num_lines
            if paragraph_id == 0: # ???
                continue
            _, data = chunks[paragraph_id]
            data.read(8)
            paragraph_dim_id = data.read_u16()
            _, paragraph_dim_data = chunks[paragraph_dim_id]
            data.read(4)
            left_margin = data.read_s16()
            cursor[0] = left_margin # TODO: idk, this might need an additional offset from page dims
            data.read(8)
            while not data.eof():
                cmd = data.read_u8()
                if cmd not in PARAGRAPH_COMMAND_LEN:
                    # TODO: maybe add something to cursor[0]
                    continue
                args = Buffer(data.read(PARAGRAPH_COMMAND_LEN[cmd]))
                if cmd == 0xc2: # picture
                    print('WARNING: inline pictures not fully implemented')
                    picture_id = args.read_u16()
                    _type, picture_data = chunks[picture_id]
                    if _type != 67:
                        print(f'WARNING: unimplemented picture type {_type}')
                        continue
                    picture_data.read(4)
                    width = picture_data.read_u16()
                    num_lines = picture_data.read_u16()
                    picture_data.read(2)
                    for _ in range(num_lines):
                        coords = decode_polyline(picture_data, cursor)
                        svg.append(drawsvg.Lines(*coords, fill='none', stroke=format_color(COLORS[0]), stroke_width=4))
                    cursor[0] += width
                elif cmd == 0xc3: # sep
                    cursor[0] += args.read_u16()
                elif cmd == 0xc4: # end
                    break
                elif cmd == 0xe5: # font
                    pass
                else:
                    print(f'WARNING: unsupported paragraph command {hex(cmd)}')

    # parse drawings (id 9)
    if 9 not in chunks:
        print('WARNING: no drawings?')
    else:
        _, data = chunks[9]
        data.read(2)
        num_drawings = data.read_u16()
        data.read(8)
        drawing_ids = []
        for _ in range(num_drawings):
            drawing_ids.append(data.read_u16())
        print('drawings:', drawing_ids)
        for drawing_id in drawing_ids:
            _, data = chunks[drawing_id]
            data.read(2)
            num_shapes = data.read_u16()
            data.read(4)
            line = data.read_u16()
            data.read(2)
            # TODO: line height? seems to be fixed at 72 for Notes?
            drawing_origin = (data.read_s16(), (line+1)*72-data.read_s16())
            drawing_size = (data.read_u16(), data.read_u16())
            data.read(8)
            shape_ids = []
            for _ in range(num_shapes):
                shape_ids.append(data.read_u16())
            print(f'drawing {drawing_id}: shapes:', shape_ids)
            bounds[0] = max(bounds[0], drawing_origin[0]+drawing_size[0])
            bounds[1] = max(bounds[1], drawing_origin[1]+drawing_size[1])
            drawing = drawsvg.Group(id=f'drawing_{drawing_id}')
            for shape_id in shape_ids:
                _type, data = chunks[shape_id]
                if _type != 103:
                    print(f'WARNING: unimplemented shape type {_type}')
                    continue
                # type 103: polyline
                data.read(3)
                color = data.read_u8()
                stroke = COLORS[color & 0xf]
                fill = COLORS[color >> 4]
                width = data.read_u8()
                is_filled = bool(data.read_u8())
                data.read(6)
                offset = (drawing_origin[0]+data.read_s16(), drawing_origin[1]+drawing_size[1]-data.read_s16())
                size = (data.read_u16(), data.read_u16())
                transform = data.read(20)
                if transform != bytes.fromhex('0000010000000100000000000000000000000000'):
                    print('WARNING: polyline transform unimplemented:', transform.hex())
                coords = decode_polyline(data, offset)
                if is_filled:
                    drawing.append(drawsvg.Lines(*coords, fill=format_color(fill), stroke=format_color(stroke), stroke_width=width, close='true'))
                else:
                    drawing.append(drawsvg.Lines(*coords, fill='none', stroke=format_color(stroke), stroke_width=width))
            svg.append(drawing)

    svg.width = bounds[0]
    svg.height = bounds[1]
    svg.view_box = (0, 0, bounds[0], bounds[1])
    svg.save_svg(sys.argv[2])

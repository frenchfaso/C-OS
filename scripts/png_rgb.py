"""Minimal RGB8 PNG reader for deterministic backend captures (standard library)."""
import binascii
import struct
import zlib


def read_rgb(path):
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Invalid PNG signature")
    offset, compressed = 8, bytearray()
    width = height = None
    while offset < len(data):
        length = struct.unpack_from(">I",data,offset)[0]
        kind = data[offset+4:offset+8]
        body = data[offset+8:offset+8+length]
        checksum = struct.unpack_from(">I",data,offset+8+length)[0]
        if binascii.crc32(kind+body)&0xffffffff != checksum:
            raise ValueError("PNG chunk checksum mismatch")
        if kind == b"IHDR":
            width,height,depth,color,compression,filtering,interlace = struct.unpack(">IIBBBBB",body)
            if (depth,color,compression,filtering,interlace) != (8,2,0,0,0):
                raise ValueError("Capture must be a non-interlaced RGB8 PNG")
        elif kind == b"IDAT":
            compressed.extend(body)
        elif kind == b"IEND":
            break
        offset += length+12
    if not width or not height or width*height > 16000000:
        raise ValueError("Invalid PNG dimensions")
    raw = zlib.decompress(compressed)
    stride = width*3
    if len(raw) != height*(stride+1):
        raise ValueError("Invalid decompressed PNG length")
    rows,previous = [],bytearray(stride)
    for y in range(height):
        kind = raw[y*(stride+1)]
        row = bytearray(raw[y*(stride+1)+1:(y+1)*(stride+1)])
        for x in range(stride):
            left = row[x-3] if x>=3 else 0
            up = previous[x]
            diagonal = previous[x-3] if x>=3 else 0
            if kind == 0:
                predictor = 0
            elif kind == 1:
                predictor = left
            elif kind == 2:
                predictor = up
            elif kind == 3:
                predictor = (left+up)//2
            elif kind == 4:
                p = left+up-diagonal
                distances = abs(p-left),abs(p-up),abs(p-diagonal)
                predictor = (left,up,diagonal)[distances.index(min(distances))]
            else:
                raise ValueError("Unknown PNG row filter")
            row[x] = (row[x]+predictor)&255
        rows.append([tuple(row[x:x+3]) for x in range(0,stride,3)])
        previous = row
    return width,height,rows

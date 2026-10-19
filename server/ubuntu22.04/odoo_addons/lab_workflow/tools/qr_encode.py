# -*- coding: utf-8 -*-
"""纯 Python 二维码编码器（Alphanumeric / Byte 模式，版本 1~20，纠错 L/M/Q/H）。

为什么自己实现
--------------
* ``reportlab`` 自带 ``graphics.barcode.qr``，但对**非 ASCII 文本**在部分小版本会
  ``TypeError``；本系统的载荷虽是 ASCII（``LABB:`` / ``LABL:``），历史标签仍可能带中文。
* 部署机是 Ubuntu 22.04 + reportlab 3.6.8，本模块**零第三方依赖**，可离线单测。
* 另提供 ``qrcode``（PyPI，BSD）交叉校验：两边都装时逐模块比对，避免生成扫不出来的码。

算法实现依据 ISO/IEC 18004（字节模式/字母数字模式、RS 纠错、8 种掩码与 4 条罚分规则）。
"""

import re

__all__ = [
    'QRCodeError',
    'ALNUM_CHARSET',
    'ALNUM_VALUES',
    'RS_BLOCK_TABLE',
    'TOTAL_CODEWORDS',
    'encode',
    'encode_matrix',
    'encode_bools',
    'module_count',
    'matrix_equal',
]

# --------------------------------------------------------------------------
# 常量（ISO/IEC 18004）
# --------------------------------------------------------------------------
ALNUM_CHARSET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'
ALNUM_VALUES = {ch: idx for idx, ch in enumerate(ALNUM_CHARSET)}

# 版本 1..40 的总码字数（= 数据 + 纠错，单位 byte）
TOTAL_CODEWORDS = (
    0,
    26, 44, 70, 100, 134, 172, 196, 242, 292, 346,
    404, 466, 532, 581, 655, 733, 815, 901, 991, 1085,
    1156, 1258, 1364, 1474, 1588, 1706, 1828, 1921, 2051, 2185,
    2323, 2465, 2611, 2761, 2876, 3034, 3196, 3362, 3532, 3706,
)

# 每个版本的 max_capacity（数据码字总数），= 总码字数 - 纠错码字数
MAX_CAPACITY = (
    0,
    19, 34, 55, 80, 108, 136, 156, 194, 232, 274,
    324, 370, 428, 461, 523, 589, 647, 721, 795, 861,
    932, 1006, 1094, 1174, 1276, 1370, 1468, 1531, 1631, 1735,
    1843, 1955, 2071, 2191, 2306, 2434, 2566, 2702, 2812, 2956,
)

# 由 ISO/IEC 18004 表 13-22 推导的 (版本, 纠错等级) -> (每块纠错码字数, [(块数, 数据码字数/块), ...])
# 生成时按「数据码字多的块在前」的官方顺序写出（见 _build_block_table）。
RS_BLOCK_STRUCTURE = {
    (1, 'L'): (7, [(1, 19)]),
    (1, 'M'): (10, [(1, 16)]),
    (1, 'Q'): (13, [(1, 13)]),
    (1, 'H'): (17, [(1, 9)]),
    (2, 'L'): (10, [(1, 34)]),
    (2, 'M'): (16, [(1, 28)]),
    (2, 'Q'): (22, [(1, 22)]),
    (2, 'H'): (28, [(1, 16)]),
    (3, 'L'): (15, [(1, 55)]),
    (3, 'M'): (26, [(1, 44)]),
    (3, 'Q'): (18, [(2, 17)]),
    (3, 'H'): (22, [(2, 13)]),
    (4, 'L'): (20, [(1, 80)]),
    (4, 'M'): (18, [(2, 32)]),
    (4, 'Q'): (26, [(2, 24)]),
    (4, 'H'): (16, [(4, 9)]),
    (5, 'L'): (26, [(1, 108)]),
    (5, 'M'): (24, [(2, 43)]),
    (5, 'Q'): (18, [(2, 15), (2, 16)]),
    (5, 'H'): (22, [(2, 11), (2, 12)]),
    (6, 'L'): (18, [(2, 68)]),
    (6, 'M'): (16, [(4, 27)]),
    (6, 'Q'): (24, [(4, 19)]),
    (6, 'H'): (28, [(4, 15)]),
    (7, 'L'): (20, [(2, 78)]),
    (7, 'M'): (18, [(4, 31)]),
    (7, 'Q'): (18, [(2, 14), (4, 15)]),
    (7, 'H'): (26, [(4, 13), (1, 14)]),
    (8, 'L'): (24, [(2, 97)]),
    (8, 'M'): (22, [(2, 38), (2, 39)]),
    (8, 'Q'): (22, [(4, 18), (2, 19)]),
    (8, 'H'): (26, [(4, 14), (2, 15)]),
    (9, 'L'): (30, [(2, 116)]),
    (9, 'M'): (22, [(3, 36), (2, 37)]),
    (9, 'Q'): (20, [(4, 16), (4, 17)]),
    (9, 'H'): (24, [(4, 12), (4, 13)]),
    (10, 'L'): (18, [(2, 68), (2, 69)]),
    (10, 'M'): (26, [(4, 43), (1, 44)]),
    (10, 'Q'): (24, [(6, 19), (2, 20)]),
    (10, 'H'): (28, [(6, 15), (2, 16)]),
    (11, 'L'): (20, [(4, 81)]),
    (11, 'M'): (30, [(1, 50), (4, 51)]),
    (11, 'Q'): (28, [(4, 22), (4, 23)]),
    (11, 'H'): (24, [(3, 12), (8, 13)]),
    (12, 'L'): (24, [(2, 92), (2, 93)]),
    (12, 'M'): (22, [(6, 36), (2, 37)]),
    (12, 'Q'): (26, [(4, 20), (6, 21)]),
    (12, 'H'): (28, [(7, 14), (4, 15)]),
    (13, 'L'): (26, [(4, 107)]),
    (13, 'M'): (22, [(8, 37), (1, 38)]),
    (13, 'Q'): (24, [(8, 20), (4, 21)]),
    (13, 'H'): (22, [(12, 11), (4, 12)]),
    (14, 'L'): (30, [(3, 115), (1, 116)]),
    (14, 'M'): (24, [(4, 40), (5, 41)]),
    (14, 'Q'): (20, [(11, 16), (5, 17)]),
    (14, 'H'): (24, [(11, 12), (5, 13)]),
    (15, 'L'): (22, [(5, 87), (1, 88)]),
    (15, 'M'): (24, [(5, 41), (5, 42)]),
    (15, 'Q'): (30, [(5, 24), (7, 25)]),
    (15, 'H'): (24, [(11, 12), (7, 13)]),
    (16, 'L'): (24, [(5, 98), (1, 99)]),
    (16, 'M'): (28, [(7, 45), (3, 46)]),
    (16, 'Q'): (24, [(15, 19), (2, 20)]),
    (16, 'H'): (30, [(3, 15), (13, 16)]),
    (17, 'L'): (28, [(1, 107), (5, 108)]),
    (17, 'M'): (28, [(10, 46), (1, 47)]),
    (17, 'Q'): (28, [(1, 22), (15, 23)]),
    (17, 'H'): (28, [(2, 14), (17, 15)]),
    (18, 'L'): (30, [(5, 120), (1, 121)]),
    (18, 'M'): (26, [(9, 43), (4, 44)]),
    (18, 'Q'): (28, [(17, 22), (1, 23)]),
    (18, 'H'): (28, [(2, 14), (19, 15)]),
    (19, 'L'): (28, [(3, 113), (4, 114)]),
    (19, 'M'): (26, [(3, 44), (11, 45)]),
    (19, 'Q'): (26, [(17, 21), (4, 22)]),
    (19, 'H'): (26, [(9, 13), (16, 14)]),
    (20, 'L'): (28, [(3, 107), (5, 108)]),
    (20, 'M'): (26, [(3, 41), (13, 42)]),
    (20, 'Q'): (30, [(15, 24), (5, 25)]),
    (20, 'H'): (28, [(15, 15), (10, 16)]),
}

# 字母数字模式每字符位数
_ALNUM_BITS = (6, 11, 13)
# 纠错等级 -> 格式信息 2bit
_EC_FORMAT_BITS = {'L': 1, 'M': 0, 'Q': 3, 'H': 2}

_VERSION_RE = re.compile(r'^[0-9]+$')


class QRCodeError(ValueError):
    """二维码参数或数据超出容量。"""


# --------------------------------------------------------------------------
# 分块表
# --------------------------------------------------------------------------
def _build_block_table():
    """(version, ec) -> (ec_codewords_per_block, [(block_count, data_codewords), ...])"""
    table = {}
    for key, (ec_per_block, groups) in RS_BLOCK_STRUCTURE.items():
        version, ec = key
        blocks = [(count, data_per_block) for count, data_per_block in groups]
        total_data = sum(count * data_per_block for count, data_per_block in groups)
        total_ec = sum(count * ec_per_block for count, _ in groups)
        total_blocks = sum(count for count, _ in groups)
        if total_data + total_ec != TOTAL_CODEWORDS[version]:
            raise QRCodeError('版本 %d-%s 总码字数不一致：%d != %d'
                              % (version, ec, total_data + total_ec, TOTAL_CODEWORDS[version]))
        table[key] = (ec_per_block, blocks, total_blocks)
    return table


RS_BLOCK_TABLE = _build_block_table()

# 对齐图形中心坐标（标准 表 E.1）
_ALIGNMENT_POSITIONS = {
    1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
    7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50],
    11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66],
    15: [6, 26, 48, 70], 16: [6, 26, 50, 74], 17: [6, 30, 54, 78],
    18: [6, 30, 56, 82], 19: [6, 30, 58, 86], 20: [6, 34, 62, 90],
}
_SKIP_ROWS = (0, 1, 2, 3, 4, 5, 6, 19, 20, 21, 22, 23)

# BCH(15,5) 生成多项式与格式信息掩码
_G15 = 0b10100110111
_G18 = 0b1111100100101
_FORMAT_MASK = 0b101010000010010
_VERSION_MASK = 0b1111100100101


# --------------------------------------------------------------------------
# GF(256) / Reed-Solomon
# --------------------------------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256


def _init_tables():
    x = 1
    for i in range(255):
        _EXP[i] = x
        _LOG[x] = i
        x <<= 1
        if x & 0x100:
            x ^= 0x11D
    for i in range(255, 512):
        _EXP[i] = _EXP[i - 255]


_init_tables()


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(degree):
    poly = [1]
    for i in range(degree):
        nxt = [0] * (len(poly) + 1)
        for j, coef in enumerate(poly):
            nxt[j] ^= _gf_mul(coef, _EXP[i])
            nxt[j + 1] ^= coef
        poly = nxt
    return poly


def _rs_encode(data, ec_length):
    gen = _rs_generator(ec_length)
    remainder = [0] * ec_length
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        if factor:
            for i, coef in enumerate(gen[1:]):
                remainder[i] ^= _gf_mul(coef, factor)
    return remainder


# --------------------------------------------------------------------------
# 位流
# --------------------------------------------------------------------------
class _BitBuffer(object):
    __slots__ = ('bits',)

    def __init__(self):
        self.bits = []

    def put(self, value, length):
        for shift in range(length - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def __len__(self):
        return len(self.bits)

    def to_bytes(self):
        while len(self.bits) % 8:
            self.bits.append(0)
        out = bytearray()
        for i in range(0, len(self.bits), 8):
            byte = 0
            for bit in self.bits[i:i + 8]:
                byte = (byte << 1) | bit
            out.append(byte)
        return bytes(out)


def _char_count_bits(version):
    return 9 if version <= 9 else 11


def _alnum_length_bits(version):
    return 9 if version <= 9 else 11


def _mode_spec(payload):
    """返回 (mode_indicator, charset_or_None)。字母数字可编码时优先字母数字模式。"""
    if payload and all(ch in ALNUM_VALUES for ch in payload):
        return 0b0010, 'alnum'
    return 0b0100, 'byte'


def _data_bit_length(payload, version, mode):
    if mode == 'alnum':
        groups, rest = divmod(len(payload), 2)
        return 4 + _alnum_length_bits(version) + groups * 11 + _ALNUM_BITS[rest]
    return 4 + _char_count_bits(version) + 8 * len(payload.encode('utf-8'))


def _data_capacity_bits(version, error_level):
    """该版本 + 纠错等级真正可用的数据位数（不含纠错码字）。"""
    _ec_per_block, groups, _blocks = RS_BLOCK_TABLE[(version, error_level)]
    data_codewords = sum(count * per_block for count, per_block in groups)
    return data_codewords * 8


def _choose_version(payload, error_level):
    for version in range(1, _MAX_VERSION + 1):
        _mode, mode = _mode_spec(payload)
        needed_bits = _data_bit_length(payload, version, mode)
        if needed_bits <= _data_capacity_bits(version, error_level):
            return version
    raise QRCodeError('内容过长（%d 字节），超出二维码版本 %d 的容量'
                      % (len(payload.encode('utf-8')), _MAX_VERSION))


_MAX_VERSION = 20


def _encode_data_bits(payload, version, error_level):
    mode_bits, mode = _mode_spec(payload)
    buf = _BitBuffer()
    buf.put(mode_bits, 4)
    if mode == 'alnum':
        buf.put(len(payload), _alnum_length_bits(version))
        index = 0
        while index + 1 < len(payload):
            buf.put(ALNUM_VALUES[payload[index]] * 45 + ALNUM_VALUES[payload[index + 1]], 11)
            index += 2
        if index < len(payload):
            buf.put(ALNUM_VALUES[payload[index]], 6)
    else:
        raw = payload.encode('utf-8')
        buf.put(len(raw), _char_count_bits(version))
        for byte in raw:
            buf.put(byte, 8)

    capacity_bits = _data_capacity_bits(version, error_level)
    if len(buf) > capacity_bits:
        raise QRCodeError('内容过长：需要 %d bit，版本 %d 只有 %d bit'
                          % (len(buf), version, capacity_bits))
    # 终止符
    remainder = capacity_bits - len(buf)
    buf.put(0, min(4, remainder))
    # 补齐到字节边界
    if len(buf) % 8:
        buf.put(0, 8 - (len(buf) % 8))
    # 填充码字 0xEC / 0x11
    pad = (capacity_bits - len(buf)) // 8
    for i in range(pad):
        buf.put(0xEC if i % 2 == 0 else 0x11, 8)
    return buf.to_bytes()


def _interleave(data_codewords, version, error_level):
    ec_per_block, groups, total_blocks = RS_BLOCK_TABLE[(version, error_level)]
    blocks = []
    offset = 0
    for count, data_per_block in groups:
        for _ in range(count):
            chunk = list(data_codewords[offset:offset + data_per_block])
            offset += data_per_block
            blocks.append(chunk)
    if offset != len(data_codewords):
        raise QRCodeError('数据码字数与分块表不一致（%d != %d）' % (offset, len(data_codewords)))
    ec_blocks = [_rs_encode(block, ec_per_block) for block in blocks]

    max_data = max(len(block) for block in blocks)
    result = []
    for i in range(max_data):
        for block in blocks:
            if i < len(block):
                result.append(block[i])
    for i in range(ec_per_block):
        for block in ec_blocks:
            result.append(block[i])
    if len(result) != TOTAL_CODEWORDS[version]:
        raise QRCodeError('交织后码字数不一致（%d != %d）'
                          % (len(result), TOTAL_CODEWORDS[version]))
    return result


# --------------------------------------------------------------------------
# 矩阵
# --------------------------------------------------------------------------
def _blank_matrix(size):
    return [[None] * size for _ in range(size)]


def _place_finder(matrix, row, col):
    size = len(matrix)
    for r in range(-1, 8):
        for c in range(-1, 8):
            rr, cc = row + r, col + c
            if 0 <= rr < size and 0 <= cc < size:
                if 0 <= r <= 6 and 0 <= c <= 6:
                    dark = r in (0, 6) or c in (0, 6) or (2 <= r <= 4 and 2 <= c <= 4)
                    matrix[rr][cc] = bool(dark)
                else:
                    matrix[rr][cc] = False


def _place_alignment(matrix, centers):
    """放置校正图形。

    只写 5x5 校正图形自身的 25 个模块；已经写好的模块（定位图形/分隔符/定时图形）
    保持原样——**不能**把 None 判断放宽成「往外扩一格」，那会覆盖数据区
    （这正是之前版本 8+ 数据错位 36 模块的根因）。
    """
    size = len(matrix)
    for row in centers:
        for col in centers:
            for r in range(-2, 3):
                for c in range(-2, 3):
                    rr, cc = row + r, col + c
                    if 0 <= rr < size and 0 <= cc < size and matrix[rr][cc] is None:
                        matrix[rr][cc] = bool(max(abs(r), abs(c)) != 1)


def _place_timing(matrix):
    size = len(matrix)
    for i in range(8, size - 8):
        value = (i % 2 == 0)
        if matrix[6][i] is None:
            matrix[6][i] = value
        if matrix[i][6] is None:
            matrix[i][6] = value


def _reserve_format_areas(matrix):
    size = len(matrix)
    for i in range(9):
        if matrix[8][i] is None:
            matrix[8][i] = False
        if matrix[i][8] is None:
            matrix[i][8] = False
    for i in range(8):
        if matrix[8][size - 1 - i] is None:
            matrix[8][size - 1 - i] = False
        if matrix[size - 1 - i][8] is None:
            matrix[size - 1 - i][8] = False
    # 固定黑模块
    matrix[size - 8][8] = True


def _format_bits(error_level, mask):
    data = (_EC_FORMAT_BITS[error_level] << 3) | mask
    value = data << 10
    rem = value
    while rem.bit_length() >= 11:
        rem ^= _G15 << (rem.bit_length() - 11)
    return ((value | rem) ^ _FORMAT_MASK) & 0x7FFF


def _version_bits(version):
    value = version << 12
    rem = value
    while rem.bit_length() >= 13:
        rem ^= _G18 << (rem.bit_length() - 13)
    return ((value | rem) ^ _VERSION_MASK) & 0x3FFFF


def _place_format(matrix, error_level, mask):
    size = len(matrix)
    bits = _format_bits(error_level, mask)
    bit_list = [(bits >> i) & 1 for i in range(15)]

    # 左上
    for i in range(6):
        matrix[8][i] = bool(bit_list[i])
    matrix[8][7] = bool(bit_list[6])
    matrix[8][8] = bool(bit_list[7])
    matrix[7][8] = bool(bit_list[8])
    for i in range(9, 15):
        matrix[14 - i][8] = bool(bit_list[i])

    # 右上 / 左下
    for i in range(8):
        matrix[8][size - 1 - i] = bool(bit_list[i])
    for i in range(8, 15):
        matrix[size - 15 + i][8] = bool(bit_list[i])


def _place_version(matrix, version):
    if version < 7:
        return
    bits = _version_bits(version)
    size = len(matrix)
    bit_list = [(bits >> i) & 1 for i in range(18)]
    for i in range(18):
        row = i // 3
        col = i % 3
        value = bool(bit_list[i])
        matrix[row][size - 8 - 3 + col] = value
        matrix[size - 8 - 3 + col][row] = value


def _mask_condition(mask, row, col):
    if mask == 0:
        return (row + col) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return col % 3 == 0
    if mask == 3:
        return (row + col) % 3 == 0
    if mask == 4:
        return (row // 2 + col // 3) % 2 == 0
    if mask == 5:
        return (row * col) % 2 + (row * col) % 3 == 0
    if mask == 6:
        return ((row * col) % 2 + (row * col) % 3) % 2 == 0
    return ((row + col) % 2 + (row * col) % 3) % 2 == 0


def _place_data(matrix, codewords, mask):
    size = len(matrix)
    bit_index = 0
    total_bits = len(codewords) * 8

    def next_bit():
        nonlocal bit_index
        if bit_index >= total_bits:
            return 0
        byte = codewords[bit_index // 8]
        bit = (byte >> (7 - (bit_index % 8))) & 1
        bit_index += 1
        return bit

    col = size - 1
    upward = True
    while col > 0:
        if col == 6:  # 跳过垂直定时图形所在的列
            col -= 1
        row_range = range(size - 1, -1, -1) if upward else range(size)
        column_pair = (col, col - 1) if col > 0 else (0,)
        for row in row_range:
            for c in column_pair:
                if matrix[row][c] is not None:
                    continue
                bit = next_bit()
                if _mask_condition(mask, row, c):
                    bit ^= 1
                matrix[row][c] = bool(bit)
        upward = not upward
        col -= 2


# --------------------------------------------------------------------------
# 罚分（掩码选择）
# --------------------------------------------------------------------------
def _penalty_n1(matrix):
    size = len(matrix)
    score = 0
    for line in list(matrix) + [[matrix[r][c] for r in range(size)] for c in range(size)]:
        run_value = line[0]
        run_length = 1
        for value in line[1:]:
            if value == run_value:
                run_length += 1
            else:
                if run_length >= 5:
                    score += 3 + (run_length - 5)
                run_value = value
                run_length = 1
        if run_length >= 5:
            score += 3 + (run_length - 5)
    return score


def _penalty_n2(matrix):
    size = len(matrix)
    score = 0
    for row in range(size - 1):
        for col in range(size - 1):
            if matrix[row][col] == matrix[row][col + 1] == matrix[row + 1][col] == matrix[row + 1][col + 1]:
                score += 3
    return score


def _penalty_n3(matrix):
    size = len(matrix)
    score = 0
    patterns = (
        (True, False, True, True, True, False, True, False, False, False, False),
        (False, False, False, False, True, False, True, True, True, False, True),
    )
    lines = list(matrix) + [[matrix[r][c] for r in range(size)] for c in range(size)]
    for line in lines:
        for i in range(len(line) - 10):
            window = tuple(line[i:i + 11])
            if window in patterns:
                score += 40
    return score


def _penalty_n4(matrix):
    dark = sum(1 for row in matrix for cell in row if cell)
    total = len(matrix) ** 2
    percent = dark * 100.0 / total
    return 10 * int(abs(percent - 50) / 5)


def _penalty(matrix):
    return _penalty_n1(matrix) + _penalty_n2(matrix) + _penalty_n3(matrix) + _penalty_n4(matrix)


# --------------------------------------------------------------------------
# 对外接口
# --------------------------------------------------------------------------
def encode(payload, error_level='M', with_mask=False):
    """编码为 ``(version, size, matrix_bool_rows, codewords[, function_mask])``。"""
    if payload is None or str(payload) == '':
        raise QRCodeError('二维码内容不能为空')
    text = str(payload)
    ec = (error_level or 'M').strip().upper()
    if ec not in ('L', 'M', 'Q', 'H'):
        ec = 'M'
    version = _choose_version(text, ec)
    data_codewords = _encode_data_bits(text, version, ec)
    codewords = _interleave(data_codewords, version, ec)
    size = 17 + 4 * version

    function_mask = None
    best = None
    for mask in range(8):
        matrix = _blank_matrix(size)
        _place_finder(matrix, 0, 0)
        _place_finder(matrix, 0, size - 7)
        _place_finder(matrix, size - 7, 0)
        _place_alignment(matrix, _ALIGNMENT_POSITIONS.get(version, []))
        _place_timing(matrix)
        _reserve_format_areas(matrix)
        _place_version(matrix, version)
        if function_mask is None:
            function_mask = [[cell is not None for cell in row] for row in matrix]
        _place_data(matrix, codewords, mask)
        _place_format(matrix, ec, mask)
        score = _penalty(matrix)
        if best is None or score < best[0]:
            best = (score, mask, matrix)
    if with_mask:
        return version, size, best[2], codewords, function_mask
    return version, size, best[2], codewords


def encode_matrix(payload, error_level='M'):
    """返回布尔矩阵（True=黑），无静区。"""
    _version, _size, matrix, _codewords = encode(payload, error_level)
    return matrix


def encode_bools(payload, error_level='M'):
    """与 :func:`encode_matrix` 相同，语义更直白。"""
    return encode_matrix(payload, error_level)


def module_count(payload, error_level='M'):
    """返回模块边长（不含静区）。"""
    version, size, _matrix, _codewords = encode(payload, error_level)
    return size


def matrix_equal(left, right):
    return [list(map(bool, row)) for row in left] == [list(map(bool, row)) for row in right]

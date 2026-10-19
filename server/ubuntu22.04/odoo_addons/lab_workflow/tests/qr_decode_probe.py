# -*- coding: utf-8 -*-
"""二维码解码校验（仅测试使用）：从矩阵逐位还原原文。

用途：验证 ``qr_encode`` 生成的矩阵**真的**符合 ISO/IEC 18004，能按标准流程解回原文。
本模块不调用 ``qr_encode._format_bits/_mask_condition`` 等内部函数，而是**独立**实现
格式信息译码、反掩码、反交织与位流解码，构成真正的交叉验证。
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.abspath(os.path.join(_HERE, '..', 'tools'))
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import qr_encode  # noqa: E402  （仅用于读取 RS 分块表/字符表等标准常量）

# ISO/IEC 18004 表 25：15 bit 格式信息（含掩码 0x5412）——独立抄录
FORMAT_INFO_TABLE = {
    ('L', 0): '111011111000100', ('L', 1): '111001011110011',
    ('L', 2): '111110110101010', ('L', 3): '111100010011101',
    ('L', 4): '110011000101111', ('L', 5): '110001100011000',
    ('L', 6): '110110001000001', ('L', 7): '110100101110110',
    ('M', 0): '101010000010010', ('M', 1): '101000100100101',
    ('M', 2): '101111001111100', ('M', 3): '101101101001011',
    ('M', 4): '100010111111001', ('M', 5): '100000011001110',
    ('M', 6): '100111110010111', ('M', 7): '100101010100000',
    ('Q', 0): '011010101011111', ('Q', 1): '011000001101000',
    ('Q', 2): '011111100110001', ('Q', 3): '011101000000110',
    ('Q', 4): '010010010110100', ('Q', 5): '010000110000011',
    ('Q', 6): '010111011011010', ('Q', 7): '010101111101101',
    ('H', 0): '001011010001001', ('H', 1): '001001110111110',
    ('H', 2): '001110011100111', ('H', 3): '001100111010000',
    ('H', 4): '000011101100010', ('H', 5): '000001001010101',
    ('H', 6): '000110100001100', ('H', 7): '000100000111011',
}

ALNUM_CHARSET = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:'


def _mask_bit(mask, row, col):
    """独立的掩码公式实现（ISO/IEC 18004 表 10）。"""
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
    if mask == 7:
        return ((row + col) % 2 + (row * col) % 3) % 2 == 0
    raise ValueError('未知掩码 %r' % (mask,))


def read_format(matrix):
    """读取并纠错左上角格式信息，返回 (ec_name, mask)。"""
    bits = 0
    for i in range(6):
        if matrix[8][i]:
            bits |= 1 << i
    if matrix[8][7]:
        bits |= 1 << 6
    if matrix[8][8]:
        bits |= 1 << 7
    if matrix[7][8]:
        bits |= 1 << 8
    for i in range(9, 15):
        if matrix[14 - i][8]:
            bits |= 1 << i

    best = None
    for (ec, mask), pattern in FORMAT_INFO_TABLE.items():
        candidate = int(pattern, 2)
        distance = bin(candidate ^ bits).count('1')
        if best is None or distance < best[0]:
            best = (distance, ec, mask)
    if best[0] > 3:
        raise ValueError('格式信息无法纠错（汉明距离 %d）' % best[0])
    return best[1], best[2]


def _is_function(row, col, size):
    """功能图形位置判定（定位/分隔/定时/格式/暗模块/校正图形区域）。"""
    if row < 9 and col < 9:
        return True
    if row < 9 and col >= size - 8:
        return True
    if row >= size - 8 and col < 9:
        return True
    if row == 6 or col == 6:
        return True
    if row == size - 8 and col == 8:  # 固定暗模块
        return True
    version = (size - 17) // 4
    centers = qr_encode._ALIGNMENT_POSITIONS.get(version, [])
    # 与编码端一致：只有 5x5 完全落在数据区（不与定位图形/分隔符重叠）的校正图形才算功能模块
    for center_row in centers:
        for center_col in centers:
            if (center_row < 7 and center_col < 7) \
                    or (center_row < 7 and center_col > size - 8) \
                    or (center_row > size - 8 and center_col < 7):
                continue
            if abs(row - center_row) <= 2 and abs(col - center_col) <= 2:
                return True
    return False


def read_codewords(matrix, mask, function_mask=None):
    size = len(matrix)
    if function_mask is None:
        function_mask = [[_is_function(row, col, size) for col in range(size)]
                         for row in range(size)]
    out_bits = []
    col = size - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        pair = (col, col - 1) if col > 0 else (0,)
        for row in rows:
            for c in pair:
                if function_mask[row][c]:
                    continue
                bit = bool(matrix[row][c]) ^ _mask_bit(mask, row, c)
                out_bits.append(1 if bit else 0)
        upward = not upward
        col -= 2

    codewords = []
    for i in range(0, len(out_bits) - 7, 8):
        byte = 0
        for bit in out_bits[i:i + 8]:
            byte = (byte << 1) | bit
        codewords.append(byte)
    return codewords


def decode(matrix, function_mask=None):
    """把矩阵解回原文（版本 1~20，字母数字/字节模式）。"""
    size = len(matrix)
    version = (size - 17) // 4
    if version < 1 or size != 17 + 4 * version:
        raise ValueError('矩阵尺寸非法：%d' % size)
    ec, mask = read_format(matrix)
    codewords = read_codewords(matrix, mask, function_mask)
    ec_per_block, groups, _blocks = qr_encode.RS_BLOCK_TABLE[(version, ec)]

    blocks = []
    for count, data_per_block in groups:
        for _ in range(count):
            blocks.append([data_per_block, []])
    max_data = max(data_per_block for _, data_per_block in groups)
    index = 0
    for i in range(max_data):
        for block in blocks:
            if i < block[0]:
                block[1].append(codewords[index])
                index += 1
    data_bytes = []
    for _length, chunk in blocks:
        data_bytes.extend(chunk)
    return _decode_bitstream(data_bytes, version)


def _decode_bitstream(data_bytes, version):
    """按 ISO 位流规则解码（支持多段：字母数字段 + 字节段 + 终止符）。"""
    bits = []
    for byte in data_bytes:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)

    def take(count):
        value = 0
        for _ in range(count):
            value = (value << 1) | bits.pop(0)
        return value

    chunks = []
    while len(bits) >= 4:
        if all(bit == 0 for bit in bits):
            break  # 剩余全是填充位
        mode = take(4)
        if mode == 0b0000:  # 终止符
            break
        if mode == 0b0010:  # 字母数字模式
            need = 9 if version <= 9 else 11
            if len(bits) < need:
                break
            length = take(need)
            chars = []
            while length >= 2:
                if len(bits) < 11:
                    raise ValueError('字母数字段被截断（剩余 %d bit）' % len(bits))
                pair = take(11)
                if pair >= 45 * 45:
                    raise ValueError('字母数字段编码越界：%d' % pair)
                chars.append(ALNUM_CHARSET[pair // 45])
                chars.append(ALNUM_CHARSET[pair % 45])
                length -= 2
            if length == 1:
                if len(bits) < 6:
                    raise ValueError('字母数字段最后一字符被截断')
                index = take(6)
                if index >= len(ALNUM_CHARSET):
                    raise ValueError('字母数字段最后一字符越界：%d' % index)
                chars.append(ALNUM_CHARSET[index])
            chunks.append(''.join(chars))
            continue
        if mode == 0b0100:  # 字节模式
            need = 8 if version <= 9 else 16
            if len(bits) < need:
                break
            length = take(need)
            if len(bits) < length * 8:
                raise ValueError('字节段被截断：需要 %d 字节，只剩 %d bit'
                                 % (length, len(bits)))
            raw = bytes(take(8) for _ in range(length))
            chunks.append(raw.decode('utf-8', 'replace'))
            continue
        raise ValueError('测试解码器不支持的模式：%s' % bin(mode))
    return ''.join(chunks)

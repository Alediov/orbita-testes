"""Keccak-256 (o hash do Ethereum) em Python puro, só para montar os seletores das funções e os tópicos dos eventos a
partir das assinaturas (`seletor("token0()")` → "0x0dfe1681"). O `hashlib.sha3_256` NÃO serve: é o SHA-3 do NIST, com
outro preenchimento. Lento (~1 ms por hash), mas só roda ao importar os módulos.
"""
from __future__ import annotations

_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def _f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak256(dados: bytes) -> bytes:
    r = 136
    p = bytearray(dados)
    p.append(1)
    while len(p) % r:
        p.append(0)
    p[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for o in range(0, len(p), r):
        for i in range(r // 8):
            a[i % 5][i // 5] ^= int.from_bytes(p[o + 8 * i:o + 8 * i + 8], "little")
        a = _f(a)
    return b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))


def seletor(assinatura: str) -> str:
    """Os 4 primeiros bytes do keccak da assinatura de uma função ("0x…")."""
    return "0x" + keccak256(assinatura.encode()).hex()[:8]


def topico(assinatura: str) -> str:
    """O tópico 0 de um evento ("0x" + 64 hex)."""
    return "0x" + keccak256(assinatura.encode()).hex()

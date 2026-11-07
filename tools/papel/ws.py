"""Cliente de websocket mínimo (RFC 6455), só biblioteca padrão, só para OUVIR: conecta, manda as mensagens de
assinatura e junta as mensagens de texto que chegarem por um tempo. Usado pelos memecoins (o PumpPortal manda os
lançamentos do pump.fun por websocket; o Python não tem websocket na biblioteca padrão e o workflow não instala nada).

Aceita `wss://` (TLS) e `ws://` (sem TLS: só nos testes, com um servidor local).
"""
from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
import time
import urllib.parse

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
UA = "orbita-testes/1"
MAX_QUADRO = 4 * 1024 * 1024


class ErroWs(Exception):
    pass


def quadro(dados: bytes, opcode=1, mascara=True) -> bytes:
    """Um quadro final (FIN) com o `opcode`; o cliente sempre mascara (exigência do protocolo)."""
    n = len(dados)
    cab = bytes([0x80 | opcode])
    m = 0x80 if mascara else 0
    if n < 126:
        cab += bytes([m | n])
    elif n < 65536:
        cab += bytes([m | 126]) + struct.pack(">H", n)
    else:
        cab += bytes([m | 127]) + struct.pack(">Q", n)
    if not mascara:
        return cab + dados
    k = os.urandom(4)
    return cab + k + bytes(b ^ k[i % 4] for i, b in enumerate(dados))


class _Leitor:
    def __init__(self, sock):
        self.sock, self.buf = sock, b""

    def ler(self, n):
        while len(self.buf) < n:
            b = self.sock.recv(65536)
            if not b:
                raise ErroWs("conexão fechada")
            self.buf += b
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def linha_ate(self, fim=b"\r\n\r\n"):
        while fim not in self.buf:
            b = self.sock.recv(4096)
            if not b:
                raise ErroWs("conexão fechada no aperto de mão")
            self.buf += b
            if len(self.buf) > 65536:
                raise ErroWs("cabeçalho grande demais")
        i = self.buf.index(fim) + len(fim)
        out, self.buf = self.buf[:i], self.buf[i:]
        return out

    def quadro(self):
        """(opcode, fin, dados)."""
        a, b = self.ler(2)
        fin, op = bool(a & 0x80), a & 0x0F
        mascarado, n = bool(b & 0x80), b & 0x7F
        if n == 126:
            n = struct.unpack(">H", self.ler(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", self.ler(8))[0]
        if n > MAX_QUADRO:
            raise ErroWs("quadro grande demais")
        k = self.ler(4) if mascarado else None
        d = self.ler(n)
        if k:
            d = bytes(x ^ k[i % 4] for i, x in enumerate(d))
        return op, fin, d


def conectar(url, prazo=20):
    u = urllib.parse.urlparse(url)
    seguro = u.scheme == "wss"
    porta = u.port or (443 if seguro else 80)
    sock = socket.create_connection((u.hostname, porta), timeout=prazo)
    if seguro:
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=u.hostname)
    chave = base64.b64encode(os.urandom(16)).decode()
    caminho = (u.path or "/") + (f"?{u.query}" if u.query else "")
    sock.sendall((f"GET {caminho} HTTP/1.1\r\nHost: {u.hostname}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Key: {chave}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: {UA}\r\n\r\n").encode())
    le = _Leitor(sock)
    cab = le.linha_ate().decode("latin-1")
    primeira = cab.split("\r\n", 1)[0]
    if " 101 " not in primeira + " ":
        sock.close()
        raise ErroWs(f"o servidor recusou o websocket: {primeira[:80]}")
    aceite = base64.b64encode(hashlib.sha1((chave + GUID).encode()).digest()).decode()
    if aceite.lower() not in cab.lower():
        sock.close()
        raise ErroWs("aceite do websocket errado")
    return sock, le


def ouvir(url, enviar, segundos, maximo, prazo=20, relogio=time.monotonic, com_hora=False):
    """Conecta, manda cada texto de `enviar` e devolve as mensagens de texto recebidas em até `segundos` (ou até
    `maximo`); com `com_hora`, pares (ms UTC da chegada, texto). Responde aos pings; para no fechamento do servidor
    (devolvendo o que já chegou)."""
    sock, le = conectar(url, prazo)
    out, partes, op_partes = [], [], None
    fim = relogio() + segundos
    try:
        for t in enviar:
            sock.sendall(quadro(t.encode()))
        while len(out) < maximo:
            falta = fim - relogio()
            if falta <= 0:
                break
            sock.settimeout(min(falta, prazo))
            try:
                op, fin, d = le.quadro()
            except (socket.timeout, TimeoutError):
                break
            except ErroWs:
                break
            if op == 9:  # ping
                sock.sendall(quadro(d, 10))
                continue
            if op == 8:  # fechou
                break
            if op in (1, 2):
                partes, op_partes = [d], op
            elif op == 0 and op_partes is not None:
                partes.append(d)
            else:
                continue
            if fin and op_partes is not None:
                if op_partes == 1:
                    txt = b"".join(partes).decode("utf-8", errors="replace")
                    out.append((int(time.time() * 1000), txt) if com_hora else txt)
                partes, op_partes = [], None
        try:
            sock.sendall(quadro(struct.pack(">H", 1000), 8))
        except OSError:
            pass
    finally:
        try:
            sock.close()
        except OSError:
            pass
    return out

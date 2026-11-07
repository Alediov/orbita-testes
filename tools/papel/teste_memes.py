"""Testes do observatório de memecoins no papel (sem rede). Uso: python3 tools/papel/teste_memes.py"""
from __future__ import annotations

import json
import os
import shutil
import socket
import struct
import sys
import tempfile
import threading

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)  # antes do mercado: os dois têm um falso.py

import falso  # noqa: E402
import memes as M  # noqa: E402
import papel  # noqa: E402
import ws  # noqa: E402
from teste_papel import conferir_forma  # noqa: E402

HORA, DIA = falso.HORA, falso.DIA
MIN = 60_000
T0 = 1_700_000_000_000 // DIA * DIA
P0 = 30.0 / (M.K_CURVA / 30.0)  # o preço do lançamento sem a compra do criador


def perto(a, b, tol=1e-6):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def ver(vid):
    return next(v for v in M.VERSOES if v[0] == vid)


def velas(precos, t0=T0, de=1):
    """Uma vela por minuto a partir do minuto `de`: (abre, máx., mín., fecha) = o mesmo preço, ou tuplas."""
    out = []
    for i, p in enumerate(precos):
        o, h, l, c = p if isinstance(p, tuple) else (p, p, p, p)
        out.append((t0 + (de + i) * MIN, o, h, l, c, 1.0))
    return out


def token(**kw):
    t = {"mint": "A" * 40 + "pump", "t": T0, "p0": P0, "rc": "ok", "cr": 0.0}
    t.update(kw)
    return t


# ------------------------------------------------------------------------------------------- a curva
def teste_curva():
    sol = 1.0
    q = M.comprar_curva(sol, P0)
    vS = 30.0 + sol
    p_depois = vS / (M.K_CURVA / vS)
    assert perto(M.vender_curva(q, p_depois), sol, 1e-9)  # vender no preço depois da própria compra devolve tudo
    assert M.vender_curva(q, P0) < sol  # vender no preço de antes: o deslize nos dois sentidos
    # com as taxas e a rede, ida e volta no mesmo preço perde ~2 × 1,25% + 2 × 0,001 SOL + o deslize
    q2, gasto = M.entrar(sol, P0, False)
    volta = M.sair(q2, p_depois, False)
    assert 0.02 < (gasto - volta) / gasto < 0.035
    # na PumpSwap: taxa + deslize fixos
    q3, _ = M.entrar(sol, P0, True)
    assert perto(q3, (sol - M.REDE_SOL) * (1 - M.TAXA_AMM) / (P0 * (1 + M.DESLIZE_AMM)))
    assert M.sair(0, P0, False) == -M.REDE_SOL
    assert perto(M.P_GRAD / P0, (115 / 30) ** 2)  # a graduação a ~14,7× o lançamento


# ------------------------------------------------------------------------------------------- as regras
def teste_regras():
    sol_usd = 100.0
    # dobra no 10º minuto: a regra do 1º minuto vende no dobro do preço de entrada
    tok = token()
    vs = velas([P0 * (1 + 0.12 * i) for i in range(30)])
    r = M.simular(tok, vs, ver("min1"), sol_usd)
    assert r[2] == "dobrou" and 5 < r[0] < 10 and r[3] == T0 + MIN
    # cai 60% no 3º minuto: −50%
    vs = velas([P0, P0, (P0, P0, P0 * 0.4, P0 * 0.4)] + [P0 * 0.4] * 30)
    r = M.simular(tok, vs, ver("min1"), sol_usd)
    assert r[2] == "−50%" and -6 < r[0] < -4.5
    # dentro da mesma vela, a pior hipótese: o −50% antes do dobro
    vs = velas([P0, (P0, P0 * 2.5, P0 * 0.4, P0)] + [P0] * 30)
    assert M.simular(tok, vs, ver("min1"), sol_usd)[2] == "−50%"
    # parado: sai em 30 min perdendo as taxas e o deslize
    vs = velas([P0] * 40)
    r = M.simular(tok, vs, ver("min1"), sol_usd)
    assert r[2] == "30 min" and -0.6 < r[0] < -0.2
    # sem nenhuma negociação: entra e sai na curva vazia (o mesmo prejuízo)
    assert -0.6 < M.simular(tok, [], ver("min1"), sol_usd)[0] < -0.2
    # momento: só entra quando passa de 60 SOL de valor de mercado
    assert M.simular(tok, velas([P0 * 1.5] * 40), ver("momento"), sol_usd) is None
    vs = velas([P0 * 1.5, P0 * 1.9, (P0 * 1.9, M.P_60 * 1.1, P0 * 1.9, M.P_60 * 1.05)] + [M.P_60 * 1.05] * 40)
    r = M.simular(tok, vs, ver("momento"), sol_usd)
    assert r and r[3] == T0 + 3 * MIN
    # RugCheck: só entra nos "ok"
    assert M.simular(token(rc="alto"), velas([P0] * 40), ver("min1rc"), sol_usd) is None
    assert M.simular(token(rc=None), velas([P0] * 40), ver("min1rc"), sol_usd) is None
    assert M.simular(token(rc="ok"), velas([P0] * 40), ver("min1rc"), sol_usd)
    # segura: vende pelo preço de ~24 h (p24); valendo 0, perde tudo
    r = M.simular(token(p24=0.0), velas([P0] * 40), ver("segura"), sol_usd)
    assert r[2] == "24 h" and r[0] < -9.9
    # graduação: entra pela hora da graduação (a PumpSwap)
    tg = T0 + 120 * MIN
    vs = velas([P0 * (1 + 0.15 * i) for i in range(200)])
    r = M.simular(token(tGrad=tg), vs, ver("graduacao"), sol_usd)
    assert r and r[3] == tg


def teste_classificar():
    # sobe 3× e cai 95% em 2 minutos (na 1ª hora): golpe e morto
    precos = [P0 * (1 + 0.2 * i) for i in range(10)] + [(P0 * 3, P0 * 3, P0 * 1.5, P0 * 1.5), P0 * 0.1] + [P0 * 0.1] * 5
    c = M.classificar(token(p24=P0 * 0.05), velas(precos))
    assert c["gp"] and c["mo"] and c["x"] >= 2.9 and not c["g"] and c["x24"] == 0.05
    # sem negociações depois do lançamento: morto, sem velas, x24 desconhecido
    c = M.classificar(token(), [])
    assert c["mo"] and c["sv"] and c["x24"] is None and c["x"] == 1
    # graduou: não conta como morto mesmo caindo depois
    c = M.classificar(token(p24=P0 * 0.05, tGrad=T0 + HORA), velas([P0 * 15] * 5))
    assert c["g"] and not c["mo"]
    # velas que faltaram (o GeckoTerminal falhou): negociou, não morreu
    c = M.classificar(token(p24=P0 * 2), [], faltou=True)
    assert not c["mo"] and not c["sv"] and c["vf"]
    n = M.contagens([M.classificar(token(p24=P0 * 0.05), velas(precos)), M.classificar(token(), []),
                     M.classificar(token(p24=P0 * 2.5), velas([P0 * 2.5] * 70))])
    assert n["tokens"] == 3 and n["golpes"] == 1 and n["dobraram"] == 2 and n["morreram"] == 2 and n["vivos24h"] == 1
    assert n["medianaX24"] == 2.5 and M.contagens([]) == {"tokens": 0}


def teste_lancamento():
    m = {"signature": "s", "mint": "Mint1111111111111111111111111111111111pump", "txType": "create", "initialBuy": 107_300_000,
         "vSolInBondingCurve": 33.0, "vTokensInBondingCurve": M.K_CURVA / 33.0, "marketCapSol": 33.8, "_t": T0 + 5000,
         "name": "nome qualquer", "symbol": "X"}
    t = M.ler_lancamento(m, T0)
    assert t["t"] == T0 + 5000 and perto(t["p0"], 33.0 / (M.K_CURVA / 33.0)) and perto(t["cr"], 0.1073)
    assert "name" not in t and "symbol" not in t  # o nome não é guardado
    assert M.ler_lancamento({"message": "Successfully subscribed"}, T0) is None
    assert M.ler_lancamento({**m, "txType": "buy"}, T0) is None
    assert M.ler_lancamento({**m, "timestamp": (T0 + 9000) / 1000}, T0)["t"] == T0 + 9000
    assert M.curto("ABCDEFGHIJKLMNOPpump") == "ABCD…pump"


# ------------------------------------------------------------------------------------------- websocket
def teste_websocket():
    """O cliente mínimo contra um servidor local: aperto de mão, assinatura, ping/pong, mensagem em pedaços e o fim."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    porta = srv.getsockname()[1]
    visto = {}

    def servidor():
        c, _ = srv.accept()
        le = ws._Leitor(c)
        cab = le.linha_ate().decode()
        chave = [x.split(": ", 1)[1] for x in cab.split("\r\n") if x.lower().startswith("sec-websocket-key")][0]
        import base64
        import hashlib
        aceite = base64.b64encode(hashlib.sha1((chave + ws.GUID).encode()).digest()).decode()
        c.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {aceite}\r\n\r\n".encode())
        op, fin, d = le.quadro()
        visto["assinatura"] = d.decode()
        c.sendall(ws.quadro(b'{"message": "ok"}', 1, mascara=False))
        c.sendall(ws.quadro(b"pi", 9, mascara=False))
        op, fin, d = le.quadro()
        visto["pong"] = (op, d)
        # uma mensagem em dois pedaços (sem FIN no 1º)
        c.sendall(bytes([0x01, 5]) + b'{"a":' + bytes([0x80, 3]) + b' 1}')
        grande = json.dumps({"x": "y" * 70_000}).encode()
        c.sendall(ws.quadro(grande, 1, mascara=False))
        c.sendall(ws.quadro(struct.pack(">H", 1000), 8, mascara=False))
        try:
            le.quadro()
        except ws.ErroWs:
            pass
        c.close()

    th = threading.Thread(target=servidor, daemon=True)
    th.start()
    msgs = ws.ouvir(f"ws://127.0.0.1:{porta}/api/data", ['{"method": "subscribeNewToken"}'], 5, 10, com_hora=True)
    th.join(5)
    srv.close()
    assert visto["assinatura"] == '{"method": "subscribeNewToken"}' and visto["pong"] == (10, b"pi")
    textos = [t for _, t in msgs]
    assert textos[0] == '{"message": "ok"}' and textos[1] == '{"a": 1}' and len(textos[2]) > 70_000 and len(textos) == 3
    assert all(isinstance(ms, int) and ms > 1e12 for ms, _ in msgs)


# ------------------------------------------------------------------------------------------- rodadas
def rodar(cli, pasta, quando, prazo=20):
    cli.agora = quando
    return papel.rodada(cli, pasta, quando, formas=["memes"], prazo_min=prazo, exemplo=True, buscar_cdi=False,
                        log=papel.Log(quieto=True))


def ler(pasta):
    with open(os.path.join(pasta, "memes.json")) as f:
        return json.load(f)


def teste_rodadas():
    a = tempfile.mkdtemp(prefix="memes-a-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        ind = rodar(cli, a, t0)
        assert ind["formas"]["memes"]["ok"]
        d = ler(a)
        conferir_forma(d, "memes")
        assert d["observatorio"]["esperando"] == M.AMOSTRA and d["observatorio"]["tudo"] == {"tokens": 0}
        assert all(v["historico"] is None for v in d["versoes"])
        # 12 h depois: amostra nova, nada analisado ainda; 24 h depois: a 1ª amostra analisada
        rodar(cli, a, t0 + 12 * HORA)
        assert ler(a)["observatorio"]["esperando"] == 2 * M.AMOSTRA
        for k in range(2, 16):
            rodar(cli, a, t0 + k * 12 * HORA)
        d = ler(a)
        conferir_forma(d, "memes")
        o = d["observatorio"]
        assert o["tudo"]["tokens"] == 14 * M.AMOSTRA and o["amostras"] == 14 and o["esperando"] == 2 * M.AMOSTRA
        assert o["tudo"]["morreram"] > o["tudo"]["tokens"] // 2 and o["tudo"]["golpes"] > 0 and o["tudo"]["dobraram"] > 0
        assert o["lancamentosPorDia"] and len(o["regras"]) == len(M.VERSOES)
        reg = {r["id"]: r for r in o["regras"]}
        assert reg["min1"]["apostas"] > reg["momento"]["apostas"] > reg["graduacao"]["apostas"] > 0
        assert reg["min1rc"]["apostas"] < reg["min1"]["apostas"]
        for v in d["versoes"]:
            av = v["aoVivo"]
            assert av and av["serie"][0][1] == 1000
            assert av["serie"][-1][1] >= 0 and av["ops"] == 2 * reg[v["id"]]["apostas"]
            assert {"apostas", "acerto", "roi", "resultado"} <= set(av["extra"])
        # os itens não trazem nomes (só o endereço encurtado)
        assert d["itens"] and all("…" in i["mint"] and "nome" not in i for i in d["itens"])
        assert "Mentira" not in json.dumps(d, ensure_ascii=False)
        assert any(e["tipo"] == "resumo" and e["versao"] is None for e in d["eventos"])
        # a DexScreener falha: a amostra fica para a próxima rodada (não conta como morta)
        n = o["tudo"]["tokens"]
        cli.falhar.add("dexscreener")
        ind = rodar(cli, a, t0 + 16 * 12 * HORA)
        assert ind["formas"]["memes"]["ok"]
        d = ler(a)
        assert d["observatorio"]["tudo"]["tokens"] == n and any("análise" in x for x in d["rodada"]["erros"])
        cli.falhar.clear()
        rodar(cli, a, t0 + 16 * 12 * HORA + HORA)
        assert ler(a)["observatorio"]["tudo"]["tokens"] > n
        # o PumpPortal falha: segue (sem amostra nova), com o erro anotado
        cli.falhar.add("pumpportal")
        ind = rodar(cli, a, t0 + 18 * 12 * HORA)
        assert ind["formas"]["memes"]["ok"] and any("PumpPortal" in x for x in ler(a)["rodada"]["erros"])
    finally:
        shutil.rmtree(a, ignore_errors=True)


if __name__ == "__main__":
    teste_curva()
    teste_regras()
    teste_classificar()
    teste_lancamento()
    teste_websocket()
    teste_rodadas()
    print("ok")

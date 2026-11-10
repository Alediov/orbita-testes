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
    # na PumpSwap: a taxa e o deslize pela conta x·y = k do pool da graduação
    q3, _ = M.entrar(sol, P0, True)
    base = (sol - M.REDE_SOL) * (1 - M.TAXA_AMM)
    assert perto(q3, M.comprar_curva(base, P0, M.K_AMM)) and q3 < base / P0
    assert M.sair(0, P0, False) == -M.REDE_SOL
    assert perto(M.P_GRAD / P0, (115 / 30) ** 2)  # a graduação a ~14,7× o lançamento
    # as partes dos custos somam a diferença para a conta sem custo nenhum
    partes = {}
    qp, _ = M.entrar(sol, P0, False, 0.002, partes)
    volta = M.sair(qp, P0, False, 0.002, partes)
    assert perto(sol - volta, sum(partes.values()), 1e-9) and partes["rede"] == 0.004 and partes["taxa"] > 0 and partes["deslize"] > 0
    # o custo de rede por operação: base + prioridade × unidades + gorjeta (sem gorjeta medida, a padrão)
    assert perto(M.custo_operacao(None, None), M.REDE_BASE_SOL + M.GORJETA_PADRAO)
    assert perto(M.custo_operacao(10_000, 0.0005), M.REDE_BASE_SOL + 10_000 * M.CU_OPERACAO / 1e15 + 0.0005)
    # o preço depois do bundle sobe pela curva
    assert M.preco_depois(P0, 3.0) > P0 and perto(M.preco_depois(P0, 0.0), P0)


def teste_estatistica():
    assert M.wilson(0, 0) is None
    lo, hi = M.wilson(10, 100)
    assert 0.05 < lo < 0.1 < hi < 0.18
    lo, hi = M.wilson(0, 20)
    assert lo == 0 and 0.1 < hi < 0.2  # nenhum em 20 ainda deixa até ~16%
    assert M.quartis([]) is None and M.quartis([1, 2, 3, 4, 5]) == [2, 3, 4]
    assert M.semana_de(T0) == "2023-W46" and M.semana_antes("2026-W01") == "2025-W52"


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
    # 1 h depois da graduação: entra 60 min depois, pelo preço do pool
    r = M.simular(token(tGrad=tg), vs, ver("grad1h"), sol_usd)
    assert r and r[3] == tg + M.HORA
    assert M.simular(token(), velas([P0] * 40), ver("grad1h"), sol_usd) is None  # não graduou
    # 1º minuto sem vela nenhuma no começo: o preço depois do bundle (não o do lançamento)
    pb = M.preco_depois(P0, 2.0)
    vs = velas([pb * 1.01] * 40, de=3)
    r1 = M.simular(token(pB=pb), vs, ver("min1"), sol_usd)
    r0 = M.simular(token(), vs, ver("min1"), sol_usd)
    assert r1[0] < r0[0]  # entrar depois dos robôs custa mais caro
    # copiar: só quando uma carteira escolhida comprou cedo, 2 min depois do lançamento
    assert M.simular(token(), velas([P0] * 40), ver("copia"), sol_usd) is None
    r = M.simular(token(copiar=True), velas([P0] * 40), ver("copia"), sol_usd)
    assert r and r[3] == T0 + M.COPIA_ATRASO * MIN
    # o custo de rede maior deixa a aposta pior; as partes somam
    partes = {}
    a = M.simular(token(), velas([P0] * 40), ver("min1"), sol_usd, 0.001, partes)[0]
    b = M.simular(token(), velas([P0] * 40), ver("min1"), sol_usd, 0.01)[0]
    assert b < a and set(partes) == {"taxa", "rede", "deslize"}


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
    # a curva: 5 min, 1 h, 6 h e 24 h (o de 7 dias vem depois); sem negócios = zeros; o golpe com os minutos até a queda
    c = M.classificar(token(p24=P0 * 0.05), velas(precos))
    assert c["c"][:4] == [round(precos[4] / P0, 4), 0.1, 0.1, 0.05] and c["c"][4] is None and c["qm"] == 12 and c["s1h"]
    c = M.classificar(token(), [])
    assert c["c"] == [0.0, 0.0, 0.0, 0.0, None] and c["s1h"]
    c = M.classificar(token(p24=P0 * 1.2), velas([P0 * 1.2] * 400))
    assert c["c"][:4] == [1.2, 1.2, 1.2, 1.2] and c["s1h"] is False
    assert M.classificar(token(), [], faltou=True)["c"] == [None] * 5


def teste_observatorio():
    """As taxas "de cada 100", a curva típica, a tabela dos sinais (só com a amostra mínima) e o medidor de golpe."""
    def r(x=1.0, x24=1.0, c=(1, 1, 1, 1, None), s1h=False, g=False, gp=False, mo=False, sg=None, gl=None, sd=False):
        o = {"t": T0, "m": "AAAA…pump", "x": x, "xs": x, "x24": x24, "c": list(c), "s1h": s1h, "g": g, "gp": gp, "mo": mo,
             "sv": False, "rc": "ok", "cr": 0, "vf": False, "sd": sd, "qm": 3 if gp else None}
        if sg is not None:
            o["sg"] = sg
        if gl is not None:
            o["gl"] = gl
        return o
    lst = [r(x=3, c=(2, 1, 1, 1, 0.6)) for _ in range(10)] + [r(x24=0, c=(0, 0, 0, 0, 0), s1h=True, mo=True) for _ in range(30)]
    lst += [r(sd=True)]
    tx = {t["id"]: t for t in M.taxas_basicas(lst)}
    assert tx["dobram"]["k"] == 10 and tx["dobram"]["n"] == 40 and tx["dobram"]["p"] == 0.25 and tx["dobram"]["ic"][0] < 0.25 < tx["dobram"]["ic"][1]
    assert tx["somem1h"]["k"] == 30 and tx["vale7d"]["k"] == 10 and tx["vale7d"]["n"] == 40
    cv = {p["id"]: p for p in M.curva_tipica(lst)}
    assert cv["5m"]["mediana"] == 0 and cv["5m"]["q3"] > 0 and cv["5m"]["n"] == 40 and cv["7d"]["n"] == 40
    # sinais: com 19 de um lado ainda não compara; com 20, compara
    sg_com, sg_sem = {"bd": 3, "cg": True, "rd": None}, {"bd": 0, "cg": False, "rd": True}
    lst = [r(x=1, x24=0.1, sg=sg_com) for _ in range(19)] + [r(x=3, x24=2, sg=sg_sem) for _ in range(25)]
    t = {x["id"]: x for x in M.tabela_sinais(lst)["linhas"]}
    assert not t["bundle"]["ok"] and t["bundle"]["com"]["n"] == 19 and t["bundle"]["sem"]["dobraram"] == 1.0
    assert t["redes"]["semDados"] == 19 and t["redes"]["com"]["n"] == 25
    lst.append(r(x=1, x24=0.1, sg=sg_com))
    t = {x["id"]: x for x in M.tabela_sinais(lst)["linhas"]}
    assert t["bundle"]["ok"] and t["bundle"]["com"]["sobreviveram"] == 0 and t["bundle"]["sem"]["sobreviveram"] == 1
    # golpe: o criador vendeu no começo (minutos), em 24 h, queda, RugCheck, liquidez; e a fração das regras
    lst = [r(gp=True, gl={"q": True, "rc": False, "cs": 4.0, "chk": 6.0, "cs24": True, "lq": False}),
           r(gl={"q": False, "rc": False, "cs": False, "chk": 7.0, "cs24": False, "lq": None}),
           r(gl={"q": False, "rc": True, "cs": None, "cs24": None, "lq": False})]
    regras = [{"id": "min1", "nome": "1º minuto", "apostas": 4, "emGolpe": 1, "resultadoGolpe": -5.0}]
    g = M.medidor_golpe(lst, regras)
    li = {x["id"]: x for x in g["linhas"]}
    assert li["criadorCedo"]["k"] == 1 and li["criadorCedo"]["n"] == 2 and li["rugcheck"]["k"] == 1 and li["qualquer"]["k"] == 2
    assert li["liquidez"]["n"] == 2 and g["minutosCriador"] == 4.0 and g["minutosQueda"] == 3 and g["regras"][0]["fracao"] == 0.25


def teste_fontes_novas():
    # os metadados: só CID do IPFS (sempre pelo ipfs.io) ou arweave; o resto não é aberto
    cid = "Qm" + "a" * 44
    assert M.url_metadados(f"https://cf-ipfs.com/ipfs/{cid}") == "https://ipfs.io/ipfs/" + cid
    assert M.url_metadados(f"ipfs://{cid}") == "https://ipfs.io/ipfs/" + cid
    assert M.url_metadados("https://site-qualquer.example/meta.json") is None and M.url_metadados(None) is None
    assert M.url_metadados("https://arweave.net/" + "b" * 43) == "https://arweave.net/" + "b" * 43
    assert M.tem_redes({"name": "x", "twitter": "https://x.com/a"}) is True
    assert M.tem_redes({"name": "x", "extensions": {"website": "https://a.b"}}) is True
    assert M.tem_redes({"name": "x", "twitter": ""}) is False and M.tem_redes("x") is None
    # a transação: quem comprou e quanto SOL
    tx = {"meta": {"err": None, "fee": 5000, "preBalances": [2_000_005_000], "postBalances": [1_000_000_000],
                   "preTokenBalances": [], "postTokenBalances": [{"owner": "W1", "mint": "M", "uiTokenAmount": {"uiAmount": 5.0}}]},
          "transaction": {"message": {"accountKeys": ["W1", "x"]}}}
    assert M.ler_tx(tx, "M") == ("W1", True, 1.0)
    assert M.ler_tx({**tx, "meta": {**tx["meta"], "err": {"x": 1}}}, "M") is None and M.ler_tx(None, "M") is None
    # o freio: depois de N falhas seguidas, para
    f = M.Freio(2)
    f.falhou("a"); f.ok(); f.falhou("b")
    assert not f.parado
    f.falhou("c")
    assert f.parado and f.motivo == "c"


def teste_copia_fora_da_amostra():
    """A seleção da semana W sai só da semana W−1 e fica guardada (não muda com o que acontece em W)."""
    est = {"carteiras": {
        "W_boa": {"s": {"2026-W45": [5, 3], "2026-W46": [5, 0]}},
        "W_media": {"s": {"2026-W45": [4, 1]}},
        "W_poucas": {"s": {"2026-W45": [2, 2]}},
        "W_zero": {"s": {"2026-W45": [9, 0]}},
        "W_depois": {"s": {"2026-W46": [9, 9]}}}}
    assert M.selecao_copia(est, "2026-W46") == ["W_boa", "W_media"]
    est["carteiras"]["W_nova"] = {"s": {"2026-W45": [9, 9]}}
    assert M.selecao_copia(est, "2026-W46") == ["W_boa", "W_media"]  # congelada
    assert M.selecao_copia(est, "2026-W47") == ["W_depois"]
    assert M.selecao_copia({"carteiras": {}}, "2026-W47", guardar=False) == []


def teste_lancamento():
    m = {"signature": "s", "mint": "Mint1111111111111111111111111111111111pump", "txType": "create", "initialBuy": 107_300_000,
         "vSolInBondingCurve": 33.0, "vTokensInBondingCurve": M.K_CURVA / 33.0, "marketCapSol": 33.8, "_t": T0 + 5000,
         "name": "nome qualquer", "symbol": "X"}
    t = M.ler_lancamento(m, T0)
    assert t["t"] == T0 + 5000 and perto(t["p0"], 33.0 / (M.K_CURVA / 33.0)) and perto(t["cr"], 0.1073)
    assert "name" not in t and "symbol" not in t  # o nome não é guardado
    t2 = M.ler_lancamento({**m, "traderPublicKey": "Criador111", "uri": "https://ipfs.io/ipfs/Qm" + "b" * 44}, T0)
    assert t2["criador"] == "Criador111" and t2["uri"].startswith("https://ipfs.io/")
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
        n1 = d["observatorio"]["esperando"]
        assert 40 <= n1 <= M.AMOSTRA and d["observatorio"]["tudo"] == {"tokens": 0}
        assert all(v["historico"] is None for v in d["versoes"])
        # os sinais anotados logo depois de ouvir ficam no estado (sem o link dos metadados nem o nome)
        with open(os.path.join(a, "estado.json")) as f:
            est_txt = f.read()
        est = json.loads(est_txt)["formas"]["memes"]
        toks = est["pendentes"][0]["tokens"]
        assert all("uri" not in t for t in toks) and "ipfs" not in est_txt and "Mentira" not in est_txt
        assert sum(1 for t in toks if t["sg"].get("bd") is not None) > len(toks) * 0.9
        assert any(t["sg"].get("rd") for t in toks) and any(t["sg"].get("rd") is False for t in toks)
        assert any(t.get("cedo") for t in toks) and any(t["sg"].get("con") for t in toks)
        assert est["pendentes"][0]["gorjeta"] == 0.0006 and est["criadores"]
        # 12 h depois: amostra nova, nada analisado ainda; 24 h depois: a 1ª amostra analisada
        rodar(cli, a, t0 + 12 * HORA)
        assert ler(a)["observatorio"]["esperando"] > n1
        for k in range(2, 22):
            rodar(cli, a, t0 + k * 12 * HORA)
        d = ler(a)
        conferir_forma(d, "memes")
        o = d["observatorio"]
        assert o["amostras"] == 20 and o["tudo"]["tokens"] > 20 * 40
        assert o["tudo"]["morreram"] > o["tudo"]["tokens"] // 2 and o["tudo"]["golpes"] > 0 and o["tudo"]["dobraram"] > 0
        assert o["lancamentosPorDia"] and len(o["regras"]) == len(M.VERSOES)
        reg = {r["id"]: r for r in o["regras"]}
        assert reg["min1"]["apostas"] > reg["momento"]["apostas"] > reg["graduacao"]["apostas"] > 0
        assert reg["grad1h"]["apostas"] > 0 and reg["min1rc"]["apostas"] < reg["min1"]["apostas"]
        assert reg["copia"]["apostas"] > 0, "a regra de copiar não achou ninguém"
        assert reg["min1"]["custoPct"] > 0.02 and set(reg["min1"]["custos"]) == {"taxa", "rede", "deslize"}
        assert 0 < reg["min1"]["emGolpe"] < reg["min1"]["apostas"]
        for v in d["versoes"]:
            av = v["aoVivo"]
            assert av and av["serie"][0][1] == 1000
            assert av["serie"][-1][1] >= 0 and av["ops"] == 2 * reg[v["id"]]["apostas"]
            assert {"apostas", "acerto", "roi", "resultado"} <= set(av["extra"])
        # 1. as taxas de cada 100 com o intervalo; a curva típica (o ponto de 7 dias já chegou)
        tx = {t["id"]: t for t in o["taxas"]}
        assert set(tx) == {"somem1h", "dobram", "vale24", "vale7d", "dez", "graduam"}
        for t in tx.values():
            assert t["n"] and t["ic"][0] <= t["p"] <= t["ic"][1], t
        assert tx["somem1h"]["p"] > 0.5 and tx["vale7d"]["n"] > 0
        cv = {p["id"]: p for p in o["curva"]}
        assert list(cv) == ["5m", "1h", "6h", "24h", "7d"] and cv["7d"]["n"] > 0 and cv["5m"]["q1"] <= cv["5m"]["mediana"] <= cv["5m"]["q3"]
        # 2. os sinais (a amostra mínima documentada)
        sn = o["sinais"]
        assert sn["minimo"] == M.MIN_SINAL and sn["tokens"] > 100 and len(sn["linhas"]) == len(M.SINAIS)
        li = {x["id"]: x for x in sn["linhas"]}
        assert li["bundle"]["ok"] and li["bundle"]["com"]["sobreviveram"] < li["bundle"]["sem"]["sobreviveram"]
        assert li["redes"]["com"]["n"] > 0 and li["criadorRepetido"]["com"]["n"] > 0
        # 5. a graduação
        gr = o["graduacao"]
        assert gr["graduaram"] > 0 and gr["taxa"] < 0.1 and gr["curva"][0]["mediana"] == 1.0 and gr["minutosMediana"]
        assert {r["id"] for r in gr["regras"]} == {"graduacao", "grad1h"}
        # 6. as carteiras que chegam cedo (só o endereço encurtado)
        cd = o["cedo"]
        assert cd["observadas"] > 0 and cd["carteiras"] and all("…" in x["carteira"] for x in cd["carteiras"])
        assert cd["carteiras"][0]["acertos"] >= cd["carteiras"][-1]["acertos"] and cd["selecao"]
        # 7. o medidor de golpe
        gl = {x["id"]: x for x in o["golpe"]["linhas"]}
        assert gl["criadorCedo"]["k"] > 0 and gl["queda"]["k"] > 0 and gl["liquidez"]["n"] > 0 and gl["qualquer"]["k"] >= gl["queda"]["k"]
        assert o["golpe"]["minutosQueda"] and len(o["golpe"]["regras"]) == len(M.VERSOES)
        # 4. os custos medidos; 3. a amostra e os pedidos por fonte
        cu = o["custos"]
        assert cu["gorjetaMedida"] and cu["gorjetaSol"] == 0.0006 and cu["porOperacaoUsd"] > 0 and cu["deslizeLancamento"] > 0
        assert o["amostra"]["porDia"] > 100 and {"solana", "gecko", "rugcheck", "ipfs", "jito"} <= set(o["amostra"]["pedidos"])
        assert o["semDados"] == []
        # só o pump.fun entra na amostra (os de outras plataformas são contados à parte)
        assert o["outrasPlataformas"] > 0 and not any(i["mint"].endswith("bonk") for i in d["itens"])
        # o GeckoTerminal confirmou os que a DexScreener não listou: nenhum ficou "sem dados" no mundo de mentira
        assert o["tudo"]["semDados"] == 0 and o["tudo"]["semNegocios"] > 0
        # os itens não trazem nomes (só o endereço encurtado); nada de link, nome ou carteira inteira no JSON
        assert d["itens"] and all("…" in i["mint"] and "nome" not in i for i in d["itens"])
        txt = json.dumps(d, ensure_ascii=False)
        assert "Mentira" not in txt and "ipfs.io/ipfs/Qm" not in txt and "exemplo.invalid" not in txt
        import falso_memes as FM
        assert not any(w in txt for w in FM.ESPERTAS + FM.SERIAIS)
        assert any(e["tipo"] == "resumo" and e["versao"] is None for e in d["eventos"])
        # a DexScreener falha: a amostra fica para a próxima rodada (não conta como morta)
        n = o["tudo"]["tokens"]
        cli.falhar.add("dexscreener")
        ind = rodar(cli, a, t0 + 22 * 12 * HORA)
        assert ind["formas"]["memes"]["ok"]
        d = ler(a)
        assert d["observatorio"]["tudo"]["tokens"] == n and any("análise" in x for x in d["rodada"]["erros"])
        cli.falhar.clear()
        rodar(cli, a, t0 + 22 * 12 * HORA + HORA)
        assert ler(a)["observatorio"]["tudo"]["tokens"] > n
        # o GeckoTerminal falha: quem a DexScreener não lista fica "sem dados" (fora das apostas), não "morto"
        cli.falhar.add("gecko")
        antes = ler(a)["observatorio"]["tudo"]
        rodar(cli, a, t0 + 23 * 12 * HORA)
        depois = ler(a)["observatorio"]["tudo"]
        assert depois["semDados"] > 0 and depois["morreram"] - antes["morreram"] < depois["tokens"] - antes["tokens"]
        cli.falhar.clear()
        # o RPC da Solana e a Jito falham: a amostra sai assim mesmo, com os sinais sem dados e o motivo
        cli.falhar.update({"solana", "jito"})
        ind = rodar(cli, a, t0 + 24 * 12 * HORA)
        d = ler(a)
        assert ind["formas"]["memes"]["ok"]
        fontes = {x["fonte"] for x in d["observatorio"]["semDados"]}
        assert {"rpc", "jito"} <= fontes, fontes
        with open(os.path.join(a, "estado.json")) as f:
            pend = json.load(f)["formas"]["memes"]["pendentes"][-1]
        assert pend["gorjeta"] is None and all(t["sg"].get("bd") is None for t in pend["tokens"])
        cli.falhar.clear()
        # o PumpPortal falha: segue (sem amostra nova), com o erro anotado
        cli.falhar.add("pumpportal")
        ind = rodar(cli, a, t0 + 25 * 12 * HORA)
        assert ind["formas"]["memes"]["ok"] and any("PumpPortal" in x for x in ler(a)["rodada"]["erros"])
    finally:
        shutil.rmtree(a, ignore_errors=True)


def teste_amostra_sorteada():
    """Acima de AMOSTRA lançamentos, o sorteio simples fica com AMOSTRA."""
    a = tempfile.mkdtemp(prefix="memes-b-")
    velho = M.AMOSTRA
    try:
        M.AMOSTRA = 10
        cli = falso.ClientePapelFalso()
        rodar(cli, a, cli.agora)
        assert ler(a)["observatorio"]["esperando"] == 10
    finally:
        M.AMOSTRA = velho
        shutil.rmtree(a, ignore_errors=True)


if __name__ == "__main__":
    teste_curva()
    teste_regras()
    teste_estatistica()
    teste_classificar()
    teste_observatorio()
    teste_fontes_novas()
    teste_copia_fora_da_amostra()
    teste_lancamento()
    teste_websocket()
    teste_rodadas()
    teste_amostra_sorteada()
    print("ok")

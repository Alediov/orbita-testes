"""Teste do ranking de palpites (concurso.py): a conta dos pontos, as estratégias, o passado e o ao vivo."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import concurso as CO  # noqa: E402

HORA = CO.HORA


def teste_pontos():
    # 3 jogos: favorito da casa que ganha, favorito de fora que perde (empate), equilibrado que dá visitante
    js = [("2026-12", "bra", [0.6, 0.25, 0.15], 0, "a", None),
          ("2026-12", "bra", [0.2, 0.3, 0.5], 1, "b", 2),
          ("2026-12", "eng", [0.38, 0.27, 0.35], 2, "c", None)]
    c = CO.contar(js)
    fav = c["fav"]["total"]
    assert (fav["palpites"], fav["acertos"], fav["pontos"]) == (3, 1, 2 - 1 - 1), fav
    assert abs(fav["esperado"] - round((3 * .6 - 1) + (3 * .5 - 1) + (3 * .38 - 1), 1)) < 1e-9
    assert c["fav50"]["total"]["palpites"] == 2 and c["fav60"]["total"]["palpites"] == 1
    emp = c["empate"]["total"]   # o 3º jogo está a 3 pontos: empate (errou)
    assert (emp["palpites"], emp["pontos"]) == (3, 2 - 1 - 1)
    assert c["casa"]["total"]["pontos"] == 2 - 1 - 1
    assert c["theo"]["total"]["palpites"] == 1 and c["theo"]["total"]["pontos"] == -1
    assert c["theoFav"]["total"]["palpites"] == 3
    assert c["azarao"]["total"]["acertos"] == 0
    assert c["fav"]["ligas"]["eng"]["pontos"] == -1 and c["fav"]["meses"]["2026-12"]["aproveitamento"] == round(1 / 3, 4)


class _D:
    def __init__(self, n):
        self.jogos = []
        for i in range(n):
            mes = "2026-%02d" % (1 + i % 5)
            p = [0.5, 0.3, 0.2]
            placar = (1, 0) if i % 2 == 0 else (0, 0)
            self.jogos.append((f"{mes}-10", "ita", placar, {"1x2": ([1.9, 3.3, 5], p, None)}))


def teste_passado_e_saida():
    assert CO.passado(_D(10)) is None
    pas = CO.passado(_D(400))
    t = pas["contas"]["fav"]["total"]
    assert t["palpites"] == 400 and t["acertos"] == 200 and t["pontos"] == 200 * 2 - 200
    assert "theo" in pas["contas"]
    C = {}
    f = {"id": 7, "i": 10 * 24 * HORA, "l": "bra", "c": "Santos", "f": "Flamengo"}
    pin = {"1x2": [[(0, 2.0)], [(0, 3.4)], [(0, 3.9)]]}
    preco_em = lambda h, t: next((p for ts, p in reversed(h) if ts <= t), None)  # noqa: E731
    sem = lambda o: [1 / x / sum(1 / y for y in o) for x in o]  # noqa: E731
    p = CO.chance_antes(pin, f["i"], sem, preco_em)
    CO.anotar(C, f, p, 2)
    CO.liquidar(C, lambda k, j: [1, 2], f["i"] + 4 * HORA)
    assert C["jogos"]["7"]["r"] == 2
    R = CO.resumo(C, _D(400), lambda ms: "2026-01-10", {"bra": "Brasileirão", "ita": "Série A"})
    es = {e["id"]: e for e in R["estrategias"]}
    assert es["theo"]["aoVivo"]["total"]["pontos"] == 2 and es["fav"]["aoVivo"]["total"]["pontos"] == -1
    assert "passado" not in es["theo"] and es["fav"]["passado"]["porMes"]["meses"] == 5
    assert R["ligas"] == {"bra": "Brasileirão", "ita": "Série A"}
    # o jogo sem placar depois de 10 dias é anulado e não conta
    CO.anotar(C, {**f, "id": 8}, p, None)
    CO.liquidar(C, lambda k, j: None, f["i"] + 11 * 24 * HORA)
    assert C["jogos"]["8"]["r"] == "anulado" and CO.ao_vivo(C, lambda ms: "2026-01-10")["jogos"] == 1


if __name__ == "__main__":
    teste_pontos()
    teste_passado_e_saida()
    print("teste_concurso: ok")

"""Roda os testes de todas as formas (teste_<forma>.py) e uma rodada completa no mercado de mentira, conferindo o
índice e o formato comum (FORMATO.md). Uso: python3 tools/papel/teste_papel.py"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "mercado"))
sys.path.insert(0, AQUI)

RISCOS = {"baixo", "médio", "alto"}


def conferir_conta(c, onde):
    if c is None:
        return
    for k in ("inicio", "serie", "retorno", "piorQueda", "ops", "taxas", "liquidacoes", "nLiq"):
        assert k in c, f"{onde}: falta {k}"
    dias = [d for d, _ in c["serie"]]
    assert dias == sorted(dias) and len(set(dias)) == len(dias), f"{onde}: série fora de ordem"
    assert 0 <= c["piorQueda"] <= 1, f"{onde}: pior queda {c['piorQueda']}"
    if c["serie"]:
        assert abs(c["serie"][-1][1] / 1000 - 1 - c["retorno"]) < 0.02, f"{onde}: retorno não bate com a série"
        m = c.get("metricas")
        assert m and {"dias", "cdi", "excesso", "venceCdi", "aoMes", "aoAno", "volAno", "sharpe", "retornoPorQueda",
                      "piorDia", "diasPositivos"} <= set(m), f"{onde}: sem as métricas comuns"
        assert m["cdi"] >= 0 and (m["aoMes"] is None) == (m["dias"] < 7), f"{onde}: métricas {m}"


def teste_metricas():
    """As métricas comuns à mão: CDI no mesmo período, excesso, Sharpe e o ao mês só com 7 dias."""
    import conta
    cdi = {f"2026-11-{d:02d}": 0.0005 for d in range(2, 30)}  # 0,05% por dia útil (aqui todos os dias da série)
    ini = 1793707200000  # 03/11/2026, 9h em Brasília
    serie = [[f"2026-11-{d:02d}", 1000 * 1.001 ** (d - 3)] for d in range(3, 24)]
    m = conta.metricas({"inicio": ini, "serie": serie, "piorQueda": 0.0}, cdi, 0.149)
    assert m["dias"] == 20 and abs(m["retorno"] - (1.001 ** 20 - 1)) < 1e-6
    assert abs(m["cdi"] - (1.0005 ** 20 - 1)) < 1e-6 and m["venceCdi"] and m["excesso"] > 0
    assert m["aoAno"] is None and m["aoMes"] is not None and m["diasPositivos"] == 1.0
    assert m["volAno"] < 1e-6 and m["sharpe"] is None  # sem oscilação, não há Sharpe
    # oscilando e perdendo do CDI: Sharpe negativo
    serie2 = [[f"2026-11-{d:02d}", 1000 * (1.004 if d % 2 else 0.997)] for d in range(3, 24)]
    m2 = conta.metricas({"inicio": ini, "serie": serie2, "piorQueda": 0.01}, cdi, 0.149)
    assert m2["sharpe"] is not None and m2["sharpe"] < 0 and not m2["venceCdi"] and m2["piorDia"] < 0
    # uma conta de 3 dias não tem ao mês (extrapolar engana)
    m3 = conta.metricas({"inicio": ini, "serie": serie[:3], "piorQueda": 0.0}, cdi, 0.149)
    assert m3["aoMes"] is None and m3["sharpe"] is None
    assert conta.cdi_ano_da_serie(cdi, 0.1) == round(1.0005 ** 252 - 1, 4) and conta.cdi_ano_da_serie({}, 0.1) == 0.1


def conferir_forma(d, nome):
    for k in ("v", "forma", "nome", "agora", "frase", "padrao", "versoes", "eventos", "avisos", "rodada"):
        assert k in d, f"{nome}: falta {k}"
    ids = [v["id"] for v in d["versoes"]]
    assert len(ids) == len(set(ids)), f"{nome}: ids repetidos"
    assert d["padrao"] in ids, f"{nome}: padrão {d['padrao']} não é uma versão"
    for v in d["versoes"]:
        assert v["risco"] in RISCOS, f"{nome}/{v['id']}: risco {v['risco']}"
        assert v.get("nome") and v.get("frase"), f"{nome}/{v['id']}: sem nome ou frase"
        conferir_conta(v.get("aoVivo"), f"{nome}/{v['id']}/aoVivo")
        conferir_conta(v.get("historico"), f"{nome}/{v['id']}/historico")
    for e in d["eventos"]:
        assert {"em", "tipo", "texto"} <= set(e), f"{nome}: evento sem campos"
    assert [e["em"] for e in d["eventos"]] == sorted((e["em"] for e in d["eventos"]), reverse=True), f"{nome}: eventos fora de ordem"
    assert len(json.dumps(d)) < 600_000, f"{nome}: grande demais"


def main():
    teste_metricas()
    falhas = []
    for t in sorted(glob.glob(os.path.join(AQUI, "teste_*.py"))):
        if t.endswith("teste_papel.py"):
            continue
        r = subprocess.run([sys.executable, t], capture_output=True, text=True)
        print(f"{os.path.basename(t)}: {'ok' if r.returncode == 0 else 'FALHOU'}")
        if r.returncode:
            falhas.append(t)
            print(r.stdout[-2000:], r.stderr[-3000:])
    import falso
    import papel
    pasta = tempfile.mkdtemp(prefix="papel-")
    try:
        cli = falso.ClientePapelFalso()
        t0 = cli.agora
        for k in range(6):
            cli.agora = t0 + k * 6 * falso.HORA
            ind = papel.rodada(cli, pasta, cli.agora, formas=papel.FORMAS + papel.FORMAS_A_PARTE, exemplo=True,
                               buscar_cdi=False, log=papel.Log(quieto=True))
        for nome, f in ind["formas"].items():
            assert f["ok"], f"{nome}: {f.get('erro')}"
            with open(os.path.join(pasta, f["arquivo"])) as fh:
                conferir_forma(json.load(fh), nome)
        assert ind["ref"]["btc"] and ind["ref"]["cdi"], "sem referências"
        assert set(ind["formas"]) == set(papel.FORMAS + papel.FORMAS_A_PARTE), sorted(ind["formas"])
        print(f"rodada completa: {sorted(ind['formas'])}")
    finally:
        shutil.rmtree(pasta, ignore_errors=True)
    if falhas:
        sys.exit(1)
    print("ok")


if __name__ == "__main__":
    main()

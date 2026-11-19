#!/usr/bin/env python3
"""Teste do emagrecimento do que é publicado (python3 tools/papel/teste_publicar.py)."""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publicar  # noqa: E402

LIGADO = {"semPassado": True, "ultimas": 6}
forma = {"forma": "robos", "versoes": [{"id": "a", "aoVivo": {"serie": [1, 2]}, "historico": {"serie": [1] * 50}},
                                       {"id": "b", "aoVivo": {"serie": [3]}}]}
resumo = {"carteiras": [{"endereco": "0x1", "aoVivo": {"1x1": {"ultimas": list(range(10)), "serie": [1]}},
                         "historico": {"1x1": {"serie": [1] * 9}}}], "ranking": [1]}

f = publicar.emagrecer_forma(copy.deepcopy(forma), LIGADO)
assert all("historico" not in v for v in f["versoes"]) and f["semPassado"] is True
assert f["versoes"][0]["aoVivo"] == {"serie": [1, 2]}, "o ao vivo não muda"
r = publicar.emagrecer_resumo(copy.deepcopy(resumo), LIGADO)
assert "historico" not in r["carteiras"][0] and r["carteiras"][0]["aoVivo"]["1x1"]["ultimas"] == [0, 1, 2, 3, 4, 5]
assert r["carteiras"][0]["aoVivo"]["1x1"]["serie"] == [1] and r["ranking"] == [1]

# desligado: nada muda
assert publicar.emagrecer_forma(copy.deepcopy(forma), {"semPassado": False, "ultimas": 0}) == forma
assert publicar.emagrecer_resumo(copy.deepcopy(resumo), {"semPassado": False, "ultimas": 0}) == resumo
# os exemplos nunca são emagrecidos
ex = dict(copy.deepcopy(forma), exemplo=True)
assert publicar.emagrecer_forma(copy.deepcopy(ex), LIGADO) == ex
exr = dict(copy.deepcopy(resumo), exemplo=True)
assert publicar.emagrecer_resumo(copy.deepcopy(exr), LIGADO) == exr
# a config de verdade (ao lado): desligada desde 19/11/2026 (o app 0.4.3 guarda os Testes fora do localStorage) e,
# com ela, o que é publicado sai inteiro
assert publicar.config().get("semPassado") is False and publicar.config().get("ultimas") == 0
assert publicar.emagrecer_forma(copy.deepcopy(forma)) == forma and publicar.emagrecer_resumo(copy.deepcopy(resumo)) == resumo
print("teste_publicar.py: ok")

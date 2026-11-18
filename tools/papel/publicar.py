"""O que vai para o app mais magro, enquanto ele guarda os Testes no localStorage (18/11/2026).

O app Órbita (até a versão 0.3.99) guarda o `resumo.json` do copy trading e todos os `<forma>.json` no localStorage do
aparelho, o MESMO lugar onde fica o progresso dos estudos, e esse lugar tem ~5,2 milhões de caracteres. Em 17/11/2026 os
Testes passaram de 3,1 milhões e o progresso (1,75 milhão) deixou de caber: o app parou de gravar o progresso sem
avisar e, a cada abertura, voltava ao último estado guardado (o Alediov refez lições).

Até o app mudar de lugar (IndexedDB, num APK novo), o que é publicado sai SEM o teste no passado de cada versão e de
cada carteira (`historico`: ~1,2 milhão de caracteres) e com as 6 últimas operações de cada conta (as que o app mostra).
O app trata a falta do `historico` como "sem teste no passado". Nada se perde: o estado dos ramos guarda tudo, e basta
pôr `semPassado` = false em `tools/papel/publicar.json` para voltar inteiro na rodada seguinte.
Os exemplos (`falso.py`, `exemplo`) nunca são emagrecidos.
"""
import json
import os

AQUI = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(AQUI, "publicar.json")     # ao lado (os workflows só trazem tools/mercado e tools/papel)
PADRAO = {"semPassado": False, "ultimas": 0}


def config(caminho=CONFIG):
    try:
        with open(caminho) as f:
            return {**PADRAO, **json.load(f)}
    except (OSError, ValueError):
        return dict(PADRAO)


def emagrecer_forma(saida, cfg=None):
    """Tira o `historico` de cada versão de um `<forma>.json`. Muda o próprio dicionário e o devolve."""
    cfg = config() if cfg is None else cfg
    if not cfg.get("semPassado") or saida.get("exemplo"):
        return saida
    tirou = 0
    for v in saida.get("versoes") or []:
        if isinstance(v, dict) and v.pop("historico", None) is not None:
            tirou += 1
    if tirou:
        saida["semPassado"] = True
    return saida


def emagrecer_resumo(resumo, cfg=None):
    """O mesmo no `resumo.json` do copy trading: sem o `historico` de cada carteira e com as últimas N operações."""
    cfg = config() if cfg is None else cfg
    if resumo.get("exemplo"):
        return resumo
    n = int(cfg.get("ultimas") or 0)
    for c in resumo.get("carteiras") or []:
        if cfg.get("semPassado") and c.pop("historico", None) is not None:
            resumo["semPassado"] = True
        if n > 0:
            for conta in (c.get("aoVivo") or {}).values():
                if isinstance(conta, dict) and isinstance(conta.get("ultimas"), list):
                    conta["ultimas"] = conta["ultimas"][:n]
    return resumo

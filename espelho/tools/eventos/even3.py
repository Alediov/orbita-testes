"""Even3 de amanhã: busca diária dos eventos online com inscrições abertas e certificado (workflow "Eventos do Even3").

Roda no GitHub Actions (o container das sessões não alcança o Even3):
  python3 tools/eventos/even3.py --dados dados [--data AAAA-MM-DD] [--depurar]

De onde vêm os eventos (descoberto em 03/11/2026):
  - a busca do site (/eventos?…, endpoint POST /auxiliar/retornarlistaevento/) manda um token do reCAPTCHA v3 a cada
    página e devolve a lista VAZIA quando a nota é baixa, que é o caso de qualquer navegador num servidor (headless,
    Chrome com janela no xvfb, sem as marcas de automação: sempre "Nenhum evento encontrado");
  - os JSONs estáticos (static.even3.com/json/lista_de_eventos-*.json) são só os destaques (~160 eventos);
  - o sitemap (robots.txt → /sitemap2/sitemap/) tem `eventoindividual-futuros_NNN` com TODOS os eventos futuros
    (~8 mil, refeito todo dia às 06h UTC), e cada página de evento traz no começo um JSON-LD schema.org Event com a
    data, o modo (Online/Offline/Mixed) e os ingressos com a disponibilidade.
Por isso: 1) lê o sitemap; 2) lê só o começo de cada página nova (ou vista há 7 dias, ou perto da data) e guarda a data
e o modo no índice `even3/indice.json`; 3) abre no Chromium só as ONLINE que começam na data e classifica pelo texto da
página e pelo JSON-LD (classificar.py).

Grava em <dados>/ (o ramo órfão `eventos`, commit único forçado; nenhum segredo):
  even3/<AAAA-MM-DD>.json  (a data dos eventos; ficam os últimos 14 dias)
  even3/ultimo.json        (cópia do último; o app lê este)
  even3/indice.json        (url → data, fim, modo, quando foi lida; o que poupa as leituras do dia seguinte)
  log.txt                  (o desta rodada em cima das anteriores, até 800 linhas)
  depuracao/paginas.json   (só com --depurar: o texto das páginas candidatas, para afinar o classificador)
Se o Even3 bloquear ou mudar, o JSON sai com `erro` (e o que deu para salvar) e o processo termina com 0.
"""
from __future__ import annotations

import argparse
import asyncio
import codecs
import datetime as dt
import json
import os
import random
import re
import sys
import time
import traceback
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import classificar as C  # noqa: E402

VERSAO = 1
BASE = "https://www.even3.com.br"
SITEMAP = BASE + "/sitemap2/sitemap/"
GUARDAR_DIAS = 14
RELER_DIAS = 7          # uma página do índice é relida depois disso (o organizador pode mudar a data ou o formato)
PERTO_DIAS = 2          # as que começam na data ou até 2 dias depois dela são relidas sempre
LER_MAX = 400_000       # bytes (descompactados) lidos no máximo do começo de cada página
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

LOG: list[str] = []
INICIO = time.time()


def log(msg: str) -> None:
    linha = f"[{time.time() - INICIO:6.1f}s] {msg}"
    LOG.append(linha)
    print(linha, flush=True)


def agora_sp() -> dt.datetime:
    """Agora em Brasília, sem fuso (o Brasil não tem horário de verão desde 2019)."""
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).replace(tzinfo=None)


def pegar(url: str, timeout: float = 40) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        corpo = r.read()
        if "gzip" in (r.headers.get("Content-Encoding") or ""):
            corpo = zlib.decompress(corpo, 16 + zlib.MAX_WBITS)
        return r.status, r.geturl(), corpo.decode("utf-8", "replace")


def subsitemaps() -> list[str]:
    """Os sub-sitemaps de eventos do índice. Em 05/11/2026 (00h32 UTC) o índice veio SEM os eventoindividual-futuros:
    tenta de novo algumas vezes (pode ser o sitemap sendo refeito), registra no log o que veio e aceita outros
    nomes de sitemap de evento individual."""
    ultimo = []
    for tentativa in range(1, 5):
        try:
            _, _, idx = pegar(SITEMAP)
            locs = [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", idx)]
            ultimo = locs
            futuros = [u for u in locs if "eventoindividual-futuros" in u]
            if futuros:
                return futuros
            log(f"sitemap (tentativa {tentativa}): {len(locs)} entradas, nenhuma eventoindividual-futuros; "
                f"amostra: {', '.join(l.rsplit('/', 2)[-2] or l for l in locs[:25])}")
        except Exception as e:
            log(f"sitemap (tentativa {tentativa}): {str(e)[:150]}")
        time.sleep(20 * tentativa)
    outros = [u for u in ultimo if re.search(r"evento-?individual|eventos?[-_]futur", u, re.I)]
    if outros:
        log(f"sitemap: usando {len(outros)} sub-sitemaps de evento com outro nome")
        return outros
    raise RuntimeError("o sitemap não tem mais os eventoindividual-futuros")


def urls_do_sitemap() -> list[str]:
    subs = subsitemaps()
    urls = []
    for s in subs:
        for tentativa in (1, 2, 3):
            try:
                _, _, t = pegar(s, timeout=60)
                urls += [u.strip() for u in re.findall(r"<loc>([^<]+)</loc>", t)]
                break
            except Exception as e:
                if tentativa == 3:
                    log(f"sitemap {s}: {str(e)[:120]}")
                time.sleep(2 * tentativa)
    return list(dict.fromkeys(urls))


def cabeca(url: str) -> dict:
    """Lê o começo da página até fechar o JSON-LD (~31 KB; sem baixar os ~430 KB inteiros). {d, f, m, nome, u} ou {erro}."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            gz = "gzip" in (r.headers.get("Content-Encoding") or "")
            dz = zlib.decompressobj(16 + zlib.MAX_WBITS) if gz else None
            dec = codecs.getincrementaldecoder("utf-8")("replace")
            buf = ""
            while len(buf) < LER_MAX:
                pedaco = r.read(16384)
                if not pedaco:
                    break
                buf += dec.decode(dz.decompress(pedaco) if dz else pedaco)
                i = buf.find("application/ld+json")
                if i >= 0 and buf.find("</script>", i) >= 0:
                    break
            final = r.geturl()
    except Exception as e:
        return {"erro": str(e)[:120]}
    rl = C.resumo_ld(C.jsonld_evento(buf))
    return {**rl, "u": final if final.rstrip("/") != url.rstrip("/") else None}


def ler_indice(caminho: str) -> dict:
    try:
        with open(caminho) as f:
            d = json.load(f)
        return d.get("eventos", {}) if d.get("versao") == 1 else {}
    except Exception:
        return {}


def atualizar_indice(urls: list[str], indice: dict, data: dt.date, prazo_s: float, paralelo: int) -> dict:
    """Lê o começo das páginas que precisam (novas, velhas ou perto da data) e devolve o índice só com as do sitemap."""
    hoje = agora_sp().date()
    de, perto = data.isoformat(), (data + dt.timedelta(days=PERTO_DIAS)).isoformat()
    novo = {u: indice[u] for u in urls if u in indice}
    precisa = []
    for u in urls:
        e = novo.get(u)
        if not e or e.get("m") == "erro":
            precisa.append(u)
            continue
        lido = dt.date.fromisoformat(e.get("t", "2000-01-01"))
        if (hoje - lido).days >= RELER_DIAS or (e.get("d") and de <= e["d"] <= perto):
            precisa.append(u)
    # as novas primeiro, depois as perto da data, depois as velhas (se o prazo acabar, fica o mais importante)
    precisa.sort(key=lambda u: (u in novo, not de <= (novo.get(u, {}).get("d") or "9") <= perto))
    log(f"índice: {len(urls)} no sitemap, {len(novo)} já conhecidas, {len(precisa)} para ler")
    limite = time.time() + prazo_s
    lidas = erros = 0
    with ThreadPoolExecutor(paralelo) as ex:
        futs = {}
        for u in precisa:
            futs[ex.submit(cabeca, u)] = u
        for f in as_completed(futs):
            u = futs[f]
            r = f.result()
            if "erro" in r:
                erros += 1
                if u not in novo:
                    novo[u] = {"m": "erro", "t": hoje.isoformat()}
                if erros <= 5:
                    log(f"  erro em {u}: {r['erro']}")
            else:
                novo[u] = {k: v for k, v in {"d": r["d"], "f": r["f"] if r["f"] != r["d"] else None, "m": r["m"],
                                              "n": r["nome"][:120], "u": r["u"], "t": hoje.isoformat()}.items() if v}
                lidas += 1
            if time.time() > limite:
                log(f"índice: o prazo acabou depois de {lidas} leituras; o resto fica para amanhã")
                for f2 in futs:
                    f2.cancel()
                break
    log(f"índice: {lidas} lidas, {erros} erros")
    return novo


async def abrir_paginas(cands: list[dict], paralelo: int, prazo_s: float) -> dict[str, dict]:
    """Abre as páginas candidatas no Chromium: {url: {texto, url_final, ld}} (ou {erro})."""
    from playwright.async_api import async_playwright
    res: dict[str, dict] = {}
    limite = time.time() + prazo_s
    async with async_playwright() as p:
        nav = await p.chromium.launch(args=["--disable-dev-shm-usage"])
        ctx = await nav.new_context(user_agent=UA, locale="pt-BR", timezone_id="America/Sao_Paulo", viewport={"width": 1280, "height": 900})

        async def leve(rota):
            if rota.request.resource_type in ("image", "media", "font"):
                await rota.abort()
            else:
                await rota.continue_()
        await ctx.route("**/*", leve)
        sem = asyncio.Semaphore(paralelo)

        async def uma(url: str):
            async with sem:
                if time.time() > limite:
                    res[url] = {"erro": "prazo"}
                    return
                pg = await ctx.new_page()
                try:
                    for tentativa in (1, 2):
                        try:
                            await pg.goto(url, wait_until="domcontentloaded", timeout=45000)
                            try:
                                await pg.wait_for_load_state("networkidle", timeout=8000)
                            except Exception:
                                pass
                            texto = await pg.evaluate("() => document.body ? document.body.innerText : ''")
                            if len(texto) < 300:
                                await pg.wait_for_timeout(3000)
                                texto = await pg.evaluate("() => document.body ? document.body.innerText : ''")
                            lds = await pg.evaluate("() => [...document.querySelectorAll('script[type=\"application/ld+json\"]')].map(s => s.textContent)")
                            ld = C.jsonld_evento("".join(f'<script type="application/ld+json">{x}</script>' for x in lds))
                            res[url] = {"texto": texto, "url_final": pg.url, "ld": ld}
                            return
                        except Exception as e:
                            if tentativa == 2:
                                res[url] = {"erro": str(e)[:200]}
                            else:
                                await pg.wait_for_timeout(2500)
                finally:
                    await pg.close()
        await asyncio.gather(*(uma(c["url"]) for c in cands))
        await nav.close()
    return res


def rodar(data: dt.date, dados: str, depurar: bool, paralelo: int, prazo_min: float, maximo: int) -> dict:
    saida: dict = {"versao": VERSAO, "fonte": "even3", "data": data.isoformat(),
                   "geradoEm": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "erro": None,
                   "criterios": "online, começa na data, inscrições abertas (REALIZAR INSCRIÇÃO e um ingresso vigente), "
                                "certificado para o participante dito na página",
                   "totalLista": 0, "analisados": 0, "eventos": [], "descartados": {}, "foraLista": []}
    cam_indice = os.path.join(dados, "even3", "indice.json")
    indice = ler_indice(cam_indice)
    prazo_s = prazo_min * 60
    try:
        urls = urls_do_sitemap()
        log(f"sitemap: {len(urls)} eventos futuros")
    except Exception as e:
        log("ERRO no sitemap: " + traceback.format_exc(limit=2))
        if not indice:
            saida["erro"] = f"Não consegui ler o sitemap do Even3: {str(e)[:200]}"
            return saida
        # sem o sitemap, o índice guardado (os eventos futuros que já conhecemos) ainda serve: as do dia e as
        # próximas são relidas; só os eventos criados depois da última leitura do sitemap ficam de fora
        urls = [u for u, e in indice.items() if not e.get("d") or e["d"] >= data.isoformat()]
        saida["aviso"] = ("O sitemap do Even3 não veio como antes; usei os eventos já conhecidos "
                          "(os criados nos últimos dias podem ficar de fora).")
        log(f"sitemap: usando o índice guardado ({len(urls)} eventos de hoje em diante)")
    indice = atualizar_indice(urls, indice, data, prazo_s * 0.55 - (time.time() - INICIO), paralelo * 3)
    os.makedirs(os.path.dirname(cam_indice), exist_ok=True)
    with open(cam_indice, "w") as f:
        json.dump({"versao": 1, "atualizado": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "eventos": indice},
                  f, ensure_ascii=False, separators=(",", ":"))
    d = data.isoformat()
    do_dia = {u: e for u, e in indice.items() if e.get("d") == d}
    modos = {}
    for e in do_dia.values():
        modos[e.get("m", "?")] = modos.get(e.get("m", "?"), 0) + 1
    log(f"{d}: {len(do_dia)} eventos começam no dia (modos {modos}); sem data no índice: "
        f"{sum(1 for e in indice.values() if not e.get('d'))}")
    saida["totalDia"] = len(do_dia)
    saida["modos"] = modos
    cands = [{"url": u, "titulo": e.get("n", ""), "resumo": ""} for u, e in do_dia.items() if e.get("m") in ("on", "?")]
    for u, e in do_dia.items():
        if e.get("m") not in ("on", "?"):
            m = "formato presencial" if e.get("m") == "off" else "formato híbrido"
            saida["descartados"][m] = saida["descartados"].get(m, 0) + 1
    saida["totalLista"] = len(cands)
    if len(cands) > maximo:
        log(f"{len(cands)} candidatas; abro só {maximo}")
        cands = cands[:maximo]
    log(f"abrindo {len(cands)} páginas online do dia")
    resto = prazo_s - (time.time() - INICIO) - 30
    paginas = asyncio.run(abrir_paginas(cands, paralelo, max(60, resto))) if cands else {}
    amostras = []
    agora = agora_sp()
    for c in cands:
        pag = paginas.get(c["url"]) or {"erro": "não abriu"}
        if pag.get("erro"):
            m = "prazo acabou" if pag["erro"] == "prazo" else "página não abriu"
            saida["descartados"][m] = saida["descartados"].get(m, 0) + 1
            saida["foraLista"].append({"nome": c["titulo"], "url": c["url"], "motivo": m + ": " + pag["erro"][:120]})
            if pag["erro"] == "prazo" and not saida["erro"]:
                saida["erro"] = "O prazo acabou antes de abrir todas as páginas do dia."
            continue
        c["url_final"] = pag["url_final"]
        item = C.analisar(c, pag["texto"], d, pag.get("ld"), agora)
        saida["analisados"] += 1
        if depurar and len(amostras) < 40:
            amostras.append({"url": c["url"], "url_final": pag["url_final"], "item": item, "ld": pag.get("ld"), "texto": pag["texto"][:15000]})
        od = " [ODONTO]" if item["odonto"]["sim"] else (" [odonto fraco]" if item["odonto"]["nivel"] == "fraco" else "")
        if item["ok"]:
            saida["eventos"].append(item)
            log(f"✓ {item['nome'][:70]}{od} — {item['inicio']}–{item['fim']} · {item['preco']} · {item['plataforma']} · cert {item['certificado']['horas']}")
        else:
            m = re.sub(r" \(.*", "", item["motivo"])
            saida["descartados"][m] = saida["descartados"].get(m, 0) + 1
            if len(saida["foraLista"]) < 400:
                saida["foraLista"].append({"nome": item["nome"], "url": item["url"], "motivo": item["motivo"], "odonto": item["odonto"]["sim"]})
            log(f"· {item['nome'][:70]}{od} — fora: {item['motivo']}")
    saida["eventos"].sort(key=lambda e: (not e["odonto"]["sim"], e["inicio"] or "99", e["nome"].lower()))
    saida["odontologia"] = sum(1 for e in saida["eventos"] if e["odonto"]["sim"])
    if depurar:
        os.makedirs(os.path.join(dados, "depuracao"), exist_ok=True)
        with open(os.path.join(dados, "depuracao", "paginas.json"), "w") as f:
            json.dump(amostras, f, ensure_ascii=False, indent=1)
    return saida


def gravar(dados: str, saida: dict) -> None:
    pasta = os.path.join(dados, "even3")
    os.makedirs(pasta, exist_ok=True)
    corpo = json.dumps(saida, ensure_ascii=False, indent=1)
    with open(os.path.join(pasta, saida["data"] + ".json"), "w") as f:
        f.write(corpo)
    with open(os.path.join(pasta, "ultimo.json"), "w") as f:
        f.write(corpo)
    corte = (agora_sp().date() - dt.timedelta(days=GUARDAR_DIAS)).isoformat()  # pelo dia de hoje (uma data pedida à mão não apaga as outras)
    for nome in os.listdir(pasta):
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.json", nome)
        if m and m.group(1) < corte:
            os.remove(os.path.join(pasta, nome))
            log(f"apaguei {nome} (mais de {GUARDAR_DIAS} dias)")


def gravar_log(dados: str) -> None:
    caminho = os.path.join(dados, "log.txt")
    antigo = []
    if os.path.exists(caminho):
        with open(caminho) as f:
            antigo = f.read().splitlines()
    cab = f"===== {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')} ====="
    linhas = ([cab] + LOG + [""] + antigo)[:800]
    with open(caminho, "w") as f:
        f.write("\n".join(linhas) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", default="dados")
    ap.add_argument("--data", default="", help="AAAA-MM-DD (padrão: amanhã em Brasília)")
    ap.add_argument("--depurar", action="store_true")
    ap.add_argument("--maximo", type=int, default=300, help="páginas de evento abertas no máximo")
    ap.add_argument("--paralelo", type=int, default=6)
    ap.add_argument("--prazo", type=float, default=25, help="minutos")
    a = ap.parse_args()
    os.makedirs(a.dados, exist_ok=True)
    random.seed()
    data = dt.date.fromisoformat(a.data.strip()) if a.data.strip() else agora_sp().date() + dt.timedelta(days=1)
    log(f"Even3 · eventos de {data.isoformat()} (agora em Brasília: {agora_sp():%Y-%m-%d %H:%M})")
    try:
        saida = rodar(data, a.dados, a.depurar, a.paralelo, a.prazo, a.maximo)
    except Exception as e:
        log("ERRO: " + traceback.format_exc(limit=4))
        saida = {"versao": VERSAO, "fonte": "even3", "data": data.isoformat(),
                 "geradoEm": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                 "erro": f"A busca falhou: {str(e)[:300]}", "eventos": [], "odontologia": 0}
    saida["duracaoS"] = round(time.time() - INICIO)
    log(f"fim: {len(saida.get('eventos', []))} eventos aceitos ({saida.get('odontologia', 0)} de Odontologia) de "
        f"{saida.get('totalLista', 0)} online no dia; descartados {saida.get('descartados', {})}; erro: {saida.get('erro')}")
    gravar(a.dados, saida)
    gravar_log(a.dados)
    return 0


if __name__ == "__main__":
    sys.exit(main())

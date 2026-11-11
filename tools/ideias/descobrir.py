"""Canais parecidos para a antena de ideias (pedido do Alediov, 11/11/2026: "aumentar o leque", com uma busca bem
menos frequente, uma vez por semana). Só SUGERE: quem decide seguir é ele, pelo app (o botão Seguir grava o canal em
`config/ideias-canais.json`; Dispensar o põe em `dispensados`, e ele não volta).

De onde vêm os candidatos (só páginas públicas, sem chave e sem conta):
1. os canais em destaque dos canais seguidos (a aba "Canais" de cada um, `/@handle/channels`);
2. a busca do YouTube filtrada por canais (`/results?search_query=…&sp=EgIQAg%3D%3D`), com as buscas de cada canal
   seguido (`buscas` na config; sem elas, o `foco` e as 3 palavras mais típicas dos títulos dele) e as `buscas` gerais;
3. os @canais citados nas descrições dos vídeos que a antena já guardou.

Para cada candidato (até `MAX_CANDIDATOS`): o channel_id (pela página do @handle, se veio sem ele) e o feed RSS (os 15
últimos vídeos). A nota (0 a 100) soma: o quanto os títulos se parecem com os de algum canal seguido (cosseno das
palavras, pesadas pela raridade), a frequência (vídeos nos últimos 30 dias), se ainda posta (último vídeo) e por quantos
caminhos ele apareceu (destaque e citação valem mais que a busca). Fica de fora: quem não posta há 60 dias, quem não
parece escrever em português (`idiomas` da config, padrão só "pt"), os seguidos e os dispensados.

Saída: `sugestoes.json` na pasta `--dados` (o ramo `ideias`): {versao, em, proxima, buscas, fontes, canais: [{chave,
nome, handle, channel_id, url, nota, parecidoCom, parecenca, videos30, ultimo, inscritos, origens, motivo, titulos,
novo}], dispensados, erros}. Roda dentro do ideias.yml, só quando a última descoberta tem 7 dias ou mais (`--cada`).

O YouTube às vezes recusa os IPs do Actions: cada fonte que falha vai para `erros`, e a rodada segue com o resto.
Uso: python3 -I tools/ideias/descobrir.py --dados dados [--config …] [--cada 7] [--falso pasta]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import glob
import html
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.normpath(os.path.join(AQUI, "..", ".."))
CONFIG = os.path.join(RAIZ, "config", "ideias-canais.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
BUSCA = "https://www.youtube.com/results?search_query={}&sp=EgIQAg%253D%253D&hl=pt-BR&gl=BR"
DESTAQUE = "https://www.youtube.com/@{}/channels?hl=pt-BR&gl=BR"
PAGINA = "https://www.youtube.com/@{}?hl=pt-BR&gl=BR"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}

VERSAO = 1
MAX_CANDIDATOS = 60
MAX_SUGESTOES = 12
POR_BUSCA = 12
NOTA_MIN = 30
PAUSA = 2.5
SEM_POSTAR_DIAS = 60
PESO_ORIGEM = {"destaque": 1.0, "citado": 0.9, "busca": 0.5}
PARADAS = set("""a o as os um uma uns umas de da do das dos em na no nas nos por para pra com sem que se e ou mas
como mais menos muito muita muitos muitas seu sua seus suas meu minha voce voces ele ela eles elas isso esse essa este
esta aqui ali ja nao sim ate sobre entre quando onde porque pq tudo todo toda todos todas cada novo nova novos novas
vai vou ser ter fazer faz fiz tem foi sao esta estao era hoje agora dia dias ano anos mes video videos canal parte
the and for with your you this that from what how why are was not but all new now get got just one two three
live ao vivo shorts short reais real""".split())
PT = set("de que nao para com uma os no se na por mais as dos como mas ao das tem seu sua ou ja quando muito nos ja "
         "esta eu tambem so pelo pela ate isso ela entre depois sem mesmo aos ter seus quem nas me esse eles voce "
         "essa num nem suas meu minha numa pelos elas qual nos lhe deles essas esses pelas este dele tu te voces "
         "como ganhar dinheiro renda gratis".split())


def agora_iso():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class Log:
    def __init__(self, eco=True):
        self.linhas, self.eco = [], eco

    def __call__(self, *partes):
        s = " ".join(str(p) for p in partes)
        self.linhas.append(f"{dt.datetime.now(dt.timezone.utc):%H:%M:%S} [descobrir] {s}")
        if self.eco:
            print(s, flush=True)


# ------------------------------------------------------------------------------------------------ texto
def dobrar(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def palavras(texto):
    return [p for p in re.findall(r"[a-z0-9]+", dobrar(texto)) if len(p) >= 4 and p not in PARADAS and not p.isdigit()]


def parece_portugues(titulos):
    ws = [w for t in titulos for w in re.findall(r"[a-z]+", dobrar(t))]
    if not ws:
        return 0.0
    return sum(1 for w in ws if w in PT) / len(ws)


class Corpus:
    """Pesos pela raridade (idf) entre todos os títulos vistos nesta rodada."""

    def __init__(self, docs):
        self.n = max(1, len(docs))
        self.df = collections.Counter()
        for d in docs:
            self.df.update(set(d))

    def vetor(self, ws):
        c = collections.Counter(ws)
        return {w: k * math.log(1 + self.n / (1 + self.df[w])) for w, k in c.items()}


def cosseno(a, b):
    if not a or not b:
        return 0.0
    num = sum(v * b.get(w, 0.0) for w, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return num / (na * nb) if na and nb else 0.0


def tipicas(ws, corpus, n=3):
    vet = corpus.vetor(ws)
    return [w for w, _ in sorted(vet.items(), key=lambda x: -x[1])[:n]]


def chave_de(handle, nome=""):
    base = dobrar(handle or nome)
    return re.sub(r"[^a-z0-9]", "", base)[:24] or "canal"


def inscritos_num(txt):
    """'1,2 mi de inscritos' → 1200000; '12,5 mil inscritos' → 12500; '987 inscritos' → 987."""
    if not txt:
        return None
    t = dobrar(txt).replace(".", "").replace(",", ".")
    m = re.search(r"([\d.]+)\s*(mil|mi|k|m)?", t)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    mult = {"mi": 1e6, "m": 1e6, "mil": 1e3, "k": 1e3}.get(m.group(2) or "", 1)
    return int(v * mult)


# ------------------------------------------------------------------------------------------------ rede
class Rede:
    def __init__(self, log, pausa=PAUSA):
        self.log, self.pausa, self.ultimo = log, pausa, 0.0

    def texto(self, url, prazo=30):
        espera = self.pausa - (time.monotonic() - self.ultimo)
        if espera > 0:
            time.sleep(espera)
        self.ultimo = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9",
                                                   "Cookie": "CONSENT=YES+1; SOCS=CAI"})
        with urllib.request.urlopen(req, timeout=prazo) as r:
            return r.read().decode("utf-8", "replace")


class RedeFalsa:
    """Para o teste: arquivos de uma pasta no lugar das páginas (nome = a url "achatada")."""

    def __init__(self, pasta, log):
        self.pasta, self.log, self.pedidos = pasta, log, []

    @staticmethod
    def nome(url):
        return re.sub(r"[^A-Za-z0-9]+", "_", url)[:180] + ".txt"

    def texto(self, url, prazo=30):
        self.pedidos.append(url)
        p = os.path.join(self.pasta, self.nome(url))
        if not os.path.exists(p):
            raise OSError(f"HTTP Error 404 (falso: {self.nome(url)})")
        with open(p, encoding="utf-8") as f:
            return f.read()


def dados_iniciais(pagina):
    """O JSON `ytInitialData` de uma página do YouTube (ou None)."""
    m = re.search(r"(?:var ytInitialData|window\[\"ytInitialData\"\])\s*=\s*", pagina)
    if not m:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(pagina[m.end():])
        return obj
    except ValueError:
        return None


def _texto(x):
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        if "simpleText" in x:
            return x["simpleText"]
        if "runs" in x:
            return "".join(r.get("text", "") for r in x["runs"])
        if "content" in x:
            return x["content"]
    return ""


def canais_no_json(obj):
    """Todo objeto com um channelId 'UC…' e um título: [{channel_id, nome, handle, inscritos, descricao}]."""
    out, vistos = [], set()

    def andar(o):
        if isinstance(o, dict):
            cid = o.get("channelId")
            nome = _texto(o.get("title")) or _texto(o.get("shortBylineText"))
            if isinstance(cid, str) and cid.startswith("UC") and nome and cid not in vistos:
                vistos.add(cid)
                url = ((o.get("navigationEndpoint") or {}).get("browseEndpoint") or {}).get("canonicalBaseUrl") or ""
                handle = url[2:] if url.startswith("/@") else ""
                if not handle:
                    m = re.search(r"@([A-Za-z0-9_.-]{3,40})", _texto(o.get("subscriberCountText")) + " " + _texto(o.get("videoCountText")))
                    handle = m.group(1) if m else ""
                insc = _texto(o.get("videoCountText")) if "inscrit" in _texto(o.get("videoCountText")).lower() else _texto(o.get("subscriberCountText"))
                out.append({"channel_id": cid, "nome": html.unescape(nome).strip(), "handle": handle,
                            "inscritos": inscritos_num(insc) if "inscrit" in insc.lower() or "subscri" in insc.lower() else None,
                            "descricao": _texto(o.get("descriptionSnippet"))[:200]})
            for v in o.values():
                andar(v)
        elif isinstance(o, list):
            for v in o:
                andar(v)
    andar(obj)
    return out


def feed(rede, channel_id):
    """Os vídeos do feed RSS: (nome do canal, [(titulo, publicado)])."""
    raiz = ET.fromstring(rede.texto(FEED.format(channel_id)))
    nome = (raiz.findtext("a:title", default="", namespaces=NS) or "").strip()
    vs = []
    for e in raiz.findall("a:entry", NS):
        vs.append((e.findtext("a:title", default="", namespaces=NS) or "", e.findtext("a:published", default="", namespaces=NS) or ""))
    return nome, vs


def channel_id_do_handle(rede, handle):
    p = rede.texto(PAGINA.format(urllib.parse.quote(handle)))
    m = re.search(r'"(?:externalId|channelId)":"(UC[\w-]{22})"', p) or re.search(r"/channel/(UC[\w-]{22})", p)
    return m.group(1) if m else None


# ------------------------------------------------------------------------------------------------ a rodada
def ler_json(p, padrao=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def dias_desde(iso, agora):
    try:
        t = dt.datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return (agora - t).total_seconds() / 86400


def precisa(dados, cada, agora):
    s = ler_json(os.path.join(dados, "sugestoes.json"))
    if not s or not s.get("em"):
        return True
    d = dias_desde(s["em"], agora)
    return d is None or d >= cada - 0.05


def videos_guardados(dados):
    out = []
    for p in glob.glob(os.path.join(dados, "videos", "*.json")):
        v = ler_json(p)
        if v:
            out.append(v)
    return out


def rodada(dados, config_path, rede, log, agora=None):
    agora = agora or dt.datetime.now(dt.timezone.utc)
    cfg = ler_json(config_path, {}) or {}
    seguidos = cfg.get("canais") or []
    idiomas = set(cfg.get("idiomas") or ["pt"])
    disp = {d.get("channel_id") for d in (cfg.get("dispensados") or []) if d.get("channel_id")}
    disp_h = {dobrar(d.get("handle") or "") for d in (cfg.get("dispensados") or []) if d.get("handle")}
    ids_seg = {c.get("channel_id") for c in seguidos if c.get("channel_id")}
    hs_seg = {dobrar(c.get("handle") or "") for c in seguidos if c.get("handle")}
    anterior = ler_json(os.path.join(dados, "sugestoes.json"), {}) or {}
    ja_sugeridos = {c["channel_id"]: c.get("primeiraVez") or anterior.get("em") for c in anterior.get("canais") or [] if c.get("channel_id")}
    ja_sugeridos.update(anterior.get("vistos") or {})
    erros = []
    fontes = collections.Counter()

    # os títulos de cada canal seguido (o que a antena guardou)
    guard = videos_guardados(dados)
    tit_seg = collections.defaultdict(list)
    for v in guard:
        if v.get("canal"):
            tit_seg[v["canal"]].append(v.get("titulo") or "")
    corpus0 = Corpus([palavras(t) for ts in tit_seg.values() for t in ts])

    candidatos = {}   # chave (channel_id ou @handle) → {…, origens: set, motivos: []}

    def anotar(c, origem, motivo, de=None, rank=0):
        k = c.get("channel_id") or ("@" + dobrar(c.get("handle") or ""))
        if not c.get("channel_id") and not c.get("handle"):
            return
        if (c.get("channel_id") in ids_seg or c.get("channel_id") in disp
                or dobrar(c.get("handle") or "") in hs_seg | disp_h):
            return
        x = candidatos.setdefault(k, {"channel_id": c.get("channel_id"), "handle": c.get("handle") or "", "nome": c.get("nome") or "",
                                      "inscritos": c.get("inscritos"), "origens": set(), "motivos": [],
                                      "de": collections.Counter(), "peso": 0.0})
        # o peso: destaque e citação valem mais que a busca; na busca, quem vem antes nos resultados vale mais
        x["peso"] += PESO_ORIGEM[origem] * (1 - min(rank, POR_BUSCA) / (2 * POR_BUSCA))
        if de:
            x["de"][de] += 1
        for campo in ("channel_id", "handle", "nome", "inscritos"):
            if not x.get(campo) and c.get(campo):
                x[campo] = c[campo]
        x["origens"].add(origem)
        if motivo not in x["motivos"]:
            x["motivos"].append(motivo)

    # 1. em destaque nos canais seguidos
    for c in seguidos:
        if not c.get("handle"):
            continue
        try:
            d = dados_iniciais(rede.texto(DESTAQUE.format(urllib.parse.quote(c["handle"]))))
            achados = [x for x in canais_no_json(d or {}) if x["channel_id"] != c.get("channel_id")]
            if not achados:   # muitos canais não têm mais a aba "Canais": os em destaque ficam na página inicial
                d = dados_iniciais(rede.texto(PAGINA.format(urllib.parse.quote(c["handle"]))))
                achados = [x for x in canais_no_json(d or {}) if x["channel_id"] != c.get("channel_id")]
            fontes["destaque"] += len(achados)
            for x in achados:
                anotar(x, "destaque", f"em destaque no {c.get('nome')}", c.get("chave"))
            log(f"destaque {c.get('chave')}: {len(achados)}")
        except Exception as e:  # noqa: BLE001
            erros.append(f"destaque {c.get('chave')}: {str(e)[:120]}")
            log(f"destaque {c.get('chave')}: {e}")

    # 2. a busca por canais
    buscas = []
    for c in seguidos:
        bs = list(c.get("buscas") or [])
        if not bs:
            # o foco dos canais seguidos pelo app é só "parecido com X": não serve de busca
            foco = "" if c.get("sugerido") else re.split(r"[(;,]", c.get("foco") or "")[0].strip()
            if foco:
                bs.append(foco)
            ws = [w for t in tit_seg.get(c.get("chave"), []) for w in palavras(t)]
            tip = tipicas(ws, corpus0)
            if len(tip) >= 2:
                bs.append(" ".join(tip))
        for b in bs[:3]:
            buscas.append((b, c.get("chave")))
    for b in cfg.get("buscas") or []:
        buscas.append((b, None))
    vistas = set()
    for b, de in buscas:
        if dobrar(b) in vistas:
            continue
        vistas.add(dobrar(b))
        try:
            d = dados_iniciais(rede.texto(BUSCA.format(urllib.parse.quote_plus(b))))
            achados = canais_no_json(d or {})[:POR_BUSCA]
            fontes["busca"] += len(achados)
            for i, x in enumerate(achados):
                anotar(x, "busca", f"busca “{b}”", de, i)
            log(f"busca “{b}”: {len(achados)}")
        except Exception as e:  # noqa: BLE001
            erros.append(f"busca “{b}”: {str(e)[:120]}")
            log(f"busca “{b}”: {e}")

    # 3. citados nas descrições
    for v in guard:
        for h in re.findall(r"(?:youtube\.com/)?@([A-Za-z0-9_.-]{3,40})", v.get("descricao") or ""):
            if "." in h and h.split(".")[-1] in ("com", "br", "net"):
                continue  # e-mail
            nome_seg = next((c.get("nome") for c in seguidos if c.get("chave") == v.get("canal")), v.get("canal"))
            anotar({"handle": h}, "citado", f"citado num vídeo do {nome_seg}", v.get("canal"))
            fontes["citado"] += 1
        for cid in re.findall(r"youtube\.com/channel/(UC[\w-]{22})", v.get("descricao") or ""):
            anotar({"channel_id": cid}, "citado", "citado numa descrição", v.get("canal"))
            fontes["citado"] += 1

    log(f"{len(candidatos)} candidatos ({dict(fontes)})")
    # os candidatos que vieram por mais caminhos primeiro
    ordem = sorted(candidatos.values(), key=lambda x: (-x["peso"], x["nome"]))[:MAX_CANDIDATOS]
    perfis = []
    for x in ordem:
        try:
            if not x["channel_id"]:
                x["channel_id"] = channel_id_do_handle(rede, x["handle"])
                if not x["channel_id"] or x["channel_id"] in ids_seg or x["channel_id"] in disp:
                    continue
            nome, vs = feed(rede, x["channel_id"])
            x["nome"] = x["nome"] or nome
            x["videos"] = vs
            perfis.append(x)
        except Exception as e:  # noqa: BLE001
            erros.append(f"feed {x.get('handle') or x.get('channel_id')}: {str(e)[:120]}")
    corpus = Corpus([palavras(t) for ts in tit_seg.values() for t in ts] + [palavras(t) for x in perfis for t, _ in x["videos"]])
    # cada seguido: as palavras dos títulos dele + o foco e as buscas (que dizem o assunto, 3 vezes)
    def palavras_seg(c):
        ws = [w for t in tit_seg.get(c.get("chave"), []) for w in palavras(t)]
        extra = palavras(" ".join([("" if c.get("sugerido") else c.get("foco") or "")] + list(c.get("buscas") or [])))
        return ws + extra * 3
    vet_seg = {c.get("chave"): corpus.vetor(palavras_seg(c)) for c in seguidos}
    ignorados = collections.Counter()
    avaliados = []
    nome_seg = {c.get("chave"): c.get("nome") for c in seguidos}
    canais = []
    for x in perfis:
        tits = [t for t, _ in x["videos"]]
        dias = [d for d in (dias_desde(p, agora) for _, p in x["videos"]) if d is not None]
        ultimo = min(dias) if dias else None
        v30 = sum(1 for d in dias if d <= 30)
        if ultimo is None or ultimo > SEM_POSTAR_DIAS:
            ignorados["sem postar"] += 1
            continue
        pt = parece_portugues(tits)
        if "pt" in idiomas and "en" not in idiomas and pt < 0.06:
            ignorados["outro idioma"] += 1
            continue
        vet = corpus.vetor([w for t in tits for w in palavras(t)])
        sims = {k: cosseno(vet, v) for k, v in vet_seg.items()}
        # o seguido mais parecido; quem levou até ele (a busca ou o destaque daquele canal) desempata
        perto = max(sims, key=lambda k: sims[k] + 0.06 * min(2, x["de"].get(k, 0))) if sims else None
        sim = sims.get(perto, 0.0) if perto else 0.0
        nota = (45 * min(1.0, sim / 0.22) + 20 * min(1.0, v30 / 8) + 15 * max(0.0, 1 - (ultimo or 60) / 30)
                + 20 * min(1.0, x["peso"] / 1.0))
        avaliados.append({"nome": x["nome"], "nota": round(nota), "parecenca": round(sim, 3), "perto": perto, "videos30": v30,
                          "pt": round(pt, 2), "peso": round(x["peso"], 2)})
        cid = x["channel_id"]
        canais.append({
            "chave": chave_de(x["handle"], x["nome"]), "nome": x["nome"], "handle": x["handle"], "channel_id": cid,
            "url": f"https://www.youtube.com/@{x['handle']}" if x["handle"] else f"https://www.youtube.com/channel/{cid}",
            "nota": round(nota), "parecidoCom": nome_seg.get(perto), "parecidoComChave": perto, "parecenca": round(sim, 3),
            "videos30": v30, "ultimo": round(ultimo, 1), "inscritos": x.get("inscritos"), "origens": sorted(x["origens"]),
            "motivo": "; ".join(x["motivos"][:3]), "titulos": tits[:4],
            "primeiraVez": ja_sugeridos.get(cid) or agora.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "novo": cid not in ja_sugeridos,
        })
    canais.sort(key=lambda c: -c["nota"])
    ignorados["nota baixa"] += sum(1 for c in canais if c["nota"] < NOTA_MIN)
    canais = [c for c in canais if c["nota"] >= NOTA_MIN][:MAX_SUGESTOES]
    vistos = dict(anterior.get("vistos") or {})
    for c in canais:
        vistos.setdefault(c["channel_id"], c["primeiraVez"])
    em = agora.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    out = {"versao": VERSAO, "em": em, "proxima": (agora + dt.timedelta(days=7)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
           "sobre": "Canais parecidos com os que a antena segue (tools/ideias/descobrir.py, 1×/semana). Só sugestões: seguir ou dispensar é no app.",
           "buscas": [b for b, _ in buscas], "fontes": dict(fontes), "candidatos": len(candidatos), "canais": canais,
           "ignorados": dict(ignorados), "avaliados": sorted(avaliados, key=lambda a: -a["nota"])[:30],
           "dispensados": len(disp), "vistos": dict(list(vistos.items())[-400:]), "erros": erros[:20]}
    with open(os.path.join(dados, "sugestoes.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    log(f"{len(canais)} sugestões; {len(erros)} erros")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", required=True)
    ap.add_argument("--config", default=CONFIG)
    ap.add_argument("--cada", type=float, default=0, help="só roda se a última descoberta tem N dias ou mais")
    ap.add_argument("--falso", help="pasta com as páginas de mentira (teste)")
    a = ap.parse_args()
    log = Log()
    agora = dt.datetime.now(dt.timezone.utc)
    if a.cada and not precisa(a.dados, a.cada, agora):
        log(f"a última descoberta tem menos de {a.cada:g} dias: nada a fazer")
        return 0
    rede = RedeFalsa(a.falso, log) if a.falso else Rede(log)
    rodada(a.dados, a.config, rede, log, agora)
    try:
        with open(os.path.join(a.dados, "log.txt"), "a", encoding="utf-8") as f:
            f.write("\n".join(log.linhas) + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

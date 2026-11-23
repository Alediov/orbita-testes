#!/usr/bin/env python3
"""Ruas de Cascavel com a geometria e os números de casa do OpenStreetMap, para pôr no mapa o endereço das fichas.

23/11/2026, pedido do Alediov (combinado com o orientador): o endereço passa a ser lido com rua e número, para marcar
os pontos exatos num mapa de calor. O ponto é calculado SÓ no computador do laboratório (o endereço não sai de lá);
este script só baixa dados PÚBLICOS do OSM (nada das fichas), por isso roda no espelho público (`dados.yml`, `qual` =
enderecos). Só biblioteca padrão.

Saída: tools/odontoscan/dados/osm-enderecos.json.gz (© colaboradores do OpenStreetMap, ODbL) e osm-enderecos-log.txt:
  ruas:    [{"n": nome, "h": tipo de via, "p": [[lon, lat], ...]}]   (uma entrada por trecho do OSM)
  numeros: [{"r": rua, "n": "123", "p": [lon, lat]}]                  (casas e lotes com addr:housenumber)
Depois, aqui no repositório do app: `python3 tools/odontoscan/geo_enderecos.py` junta os trechos e gera o que o
Scanner usa.
"""
import gzip
import json
import sys
import time
import traceback
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
DADOS = RAIZ / "tools/odontoscan/dados"
SAIDA = DADOS / "osm-enderecos.json.gz"
LOG_ARQ = DADOS / "osm-enderecos-log.txt"
# a área urbana de Cascavel (os bairros do GeoCascavel) com ~2 km de folga; os distritos ficam pelo centro do bairro
BBOX = (-25.025, -53.55, -24.88, -53.36)  # sul, oeste, norte, leste
SERVIDORES = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
              "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def overpass(q):
    corpo = urllib.parse.urlencode({"data": q}).encode()
    erro = None
    for tentativa in range(3):
        for url in SERVIDORES:
            try:
                req = urllib.request.Request(url, data=corpo, headers={"User-Agent": "orbita-odontoscan/1.0 (dados públicos)"})
                with urllib.request.urlopen(req, timeout=900) as r:
                    j = json.loads(r.read())
                log(f"Overpass ok em {url}: {len(j.get('elements', []))} elementos")
                return j
            except Exception as e:  # servidor ocupado: tenta o próximo
                erro = e
                log(f"Overpass falhou em {url}: {e}")
        time.sleep(30 * (tentativa + 1))
    raise RuntimeError(f"Overpass não respondeu: {erro}")


def r5(v):
    return round(v, 6)


def main():
    s, o, n, l = BBOX
    bbox = f"{s},{o},{n},{l}"
    j = overpass(f"""[out:json][timeout:900];
(
  way["highway"]["name"]({bbox});
  node["addr:housenumber"]({bbox});
  way["addr:housenumber"]({bbox});
);
out geom;""")
    ruas, numeros = [], []
    for el in j.get("elements", []):
        t = el.get("tags", {})
        if el["type"] == "way" and "highway" in t and t.get("name"):
            pts = [[r5(p["lon"]), r5(p["lat"])] for p in el.get("geometry", []) if p]
            if len(pts) >= 2:
                ruas.append({"n": t["name"].strip(), "h": t["highway"], "p": pts})
        if t.get("addr:housenumber") and t.get("addr:street"):
            if el["type"] == "node":
                p = [r5(el["lon"]), r5(el["lat"])]
            else:
                g = [x for x in el.get("geometry", []) if x]
                if not g:
                    continue
                p = [r5(sum(x["lon"] for x in g) / len(g)), r5(sum(x["lat"] for x in g) / len(g))]
            numeros.append({"r": t["addr:street"].strip(), "n": t["addr:housenumber"].strip(), "p": p})
    nomes = {r["n"] for r in ruas}
    log(f"{len(ruas)} trechos de rua com nome ({len(nomes)} nomes), {len(numeros)} endereços com número "
        f"({len({x['r'] for x in numeros})} ruas com algum número)")
    saida = {"fonte": "OpenStreetMap (© colaboradores do OpenStreetMap, ODbL)", "gerado": time.strftime("%Y-%m-%d"),
             "bbox": BBOX, "ruas": ruas, "numeros": numeros}
    DADOS.mkdir(parents=True, exist_ok=True)
    SAIDA.write_bytes(gzip.compress(json.dumps(saida, ensure_ascii=False, separators=(",", ":")).encode(), 9))
    log(f"gravado {SAIDA.name}: {SAIDA.stat().st_size // 1024} KB")


if __name__ == "__main__":
    ok = True
    try:
        main()
    except Exception:
        ok = False
        log(traceback.format_exc())
    DADOS.mkdir(parents=True, exist_ok=True)
    LOG_ARQ.write_text("\n".join(LOG) + "\n", encoding="utf-8")
    sys.exit(0 if ok else 1)

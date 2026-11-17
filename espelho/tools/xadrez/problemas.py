#!/usr/bin/env python3
"""Separa problemas do banco do Lichess (CC0, database.lichess.org) para os treinos semanais do Xadrez do Órbita.

Roda no GitHub Actions (a sessão não alcança o Lichess): baixa lichess_db_puzzle.csv.zst, filtra problemas populares
e bem avaliados entre 400 e 1800 de rating e grava app/dados/xadrez/problemas.json com até N por tema (espalhados
pelas faixas de rating), mais os que saíram de partidas nas aberturas do repertório dele.
"""
import csv
import io
import json
import random
import sys
import urllib.request
from pathlib import Path

import zstandard

URL = "https://database.lichess.org/lichess_db_puzzle.csv.zst"
SAIDA = Path("app/dados/xadrez/problemas.json")
POR_TEMA = 150
FAIXAS = [(400, 800), (800, 1100), (1100, 1400), (1400, 1800)]

# tema do app -> temas do Lichess (qualquer um)
TEMAS = {
    "mate1": ["mateIn1"], "mate2": ["mateIn2"], "mate3": ["mateIn3"],
    "corredor": ["backRankMate"], "garfo": ["fork"], "cravada": ["pin"], "espeto": ["skewer"],
    "descoberto": ["discoveredAttack"], "xequeDuplo": ["doubleCheck"], "pendurada": ["hangingPiece"],
    "presa": ["trappedPiece"], "desvio": ["deflection"], "atracao": ["attraction"], "sacrificio": ["sacrifice"],
    "defesa": ["defensiveMove"], "peaoAvancado": ["advancedPawn", "promotion"], "intermediario": ["intermezzo"],
    "finalPeoes": ["pawnEndgame"], "finalTorre": ["rookEndgame"], "finalDama": ["queenEndgame"], "finalBispoCavalo": ["bishopEndgame", "knightEndgame"],
}
# as aberturas do repertório (OpeningTags do Lichess começam por estes nomes)
ABERTURAS = {
    "sicilianaTaimanov": ["Sicilian_Defense_Taimanov_Variation"], "sicilianaAlapin": ["Sicilian_Defense_Alapin_Variation"],
    "sicilianaOutras": ["Sicilian_Defense_Closed", "Sicilian_Defense_Smith-Morra_Gambit", "Sicilian_Defense_McDonnell_Attack", "Sicilian_Defense_French_Variation"],
    "italiana": ["Italian_Game"], "petrovPhilidor": ["Petrovs_Defense", "Philidor_Defense"],
    "gambitoDamaRecusado": ["Queens_Gambit_Declined"], "londres": ["Queens_Pawn_Game_London_System", "Queens_Pawn_Game_Accelerated_London_System"],
    "francesaAvanco": ["French_Defense_Advance_Variation"], "caroKannAvanco": ["Caro-Kann_Defense_Advance_Variation"],
    "escandinava": ["Scandinavian_Defense"], "pircModerna": ["Pirc_Defense", "Modern_Defense"], "alekhine": ["Alekhine_Defense"],
    # repertório 2 (02/11/2026): Escocesa, Quatro Cavalos da Siciliana, Grünfeld, o Gambito da Dama inteiro e a Eslava
    "escocesa": ["Scotch_Game"], "sicilianaQuatroCavalos": ["Sicilian_Defense_Four_Knights_Variation", "Sicilian_Defense_Scheveningen_Variation"],
    "grunfeld": ["Grunfeld_Defense", "Neo-Grunfeld_Defense"], "gambitoDamaAceito": ["Queens_Gambit_Accepted"],
    "eslava": ["Slav_Defense", "Semi-Slav_Defense"],
}


def main():
    print("baixando", URL, flush=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "orbita-xadrez (uso pessoal)"})
    bruto = urllib.request.urlopen(req, timeout=600)
    texto = io.TextIOWrapper(zstandard.ZstdDecompressor().stream_reader(bruto), encoding="utf-8")
    grupos = {k: [] for k in list(TEMAS) + list(ABERTURAS)}
    n = 0
    for r in csv.DictReader(texto):
        n += 1
        if n % 500000 == 0:
            print(n, "linhas", flush=True)
        try:
            rating, pop, jogadas, desvio = int(r["Rating"]), int(r["Popularity"]), int(r["NbPlays"]), int(r["RatingDeviation"])
        except (ValueError, KeyError):
            continue
        if not (400 <= rating < 1800) or pop < 85 or jogadas < 300 or desvio > 90:
            continue
        temas = set(r["Themes"].split())
        aberturas = r.get("OpeningTags", "").split()
        p = (r["PuzzleId"], r["FEN"], r["Moves"], rating, pop, r["Themes"])
        for k, ts in TEMAS.items():
            if temas.intersection(ts):
                grupos[k].append(p)
        for k, prefs in ABERTURAS.items():
            if any(a.startswith(pr) for a in aberturas for pr in prefs):
                grupos[k].append(p)
    print("lidas", n, flush=True)
    random.seed(25102026)
    problemas, temas_out = {}, {}
    for k, lista in grupos.items():
        escolhidos = []
        for lo, hi in FAIXAS:
            faixa = sorted([p for p in lista if lo <= p[3] < hi], key=lambda p: -p[4])[:POR_TEMA * 3]
            random.shuffle(faixa)
            escolhidos += faixa[:POR_TEMA // len(FAIXAS)]
        escolhidos.sort(key=lambda p: p[3])
        temas_out[k] = [p[0] for p in escolhidos]
        for p in escolhidos:
            problemas[p[0]] = [p[1], p[2], p[3], p[5]]
        print(k, len(lista), "->", len(escolhidos))
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps({"fonte": "Lichess puzzle database (CC0), database.lichess.org", "temas": temas_out, "problemas": problemas},
                                separators=(",", ":")))
    print(SAIDA, SAIDA.stat().st_size, "bytes,", len(problemas), "problemas")


if __name__ == "__main__":
    sys.exit(main())

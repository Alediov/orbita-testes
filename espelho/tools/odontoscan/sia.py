#!/usr/bin/env python3
"""Produção ambulatorial OFICIAL (SIA/SUS, DATASUS) dos dois estabelecimentos da clínica de Odontologia da UNIOESTE,
para o Scanner comparar com as fichas digitalizadas ("Comparar com o oficial", pedido do Alediov em 25/10/2026):

    CNES 3523365  Unioeste Odontologia
    CNES 6391915  CEO III Unioeste

Lê os arquivos PA (produção ambulatorial) do Paraná no FTP do DATASUS (SIASUS/200801_/Dados/PAPRaamm*.dbc), um por
mês de processamento; descompacta o .dbc (pyreaddbc ou datasus-dbc) e lê o .dbf direto com numpy (registros de
tamanho fixo), ficando só com as linhas dos dois CNES. Soma por competência (PA_CMP, o mês do atendimento):
procedimento (apresentado, aprovado e valor aprovado), município de residência do paciente e sexo/faixa etária.

Só dados públicos e agregados. Roda no GitHub Actions (workflow "Dados do SIA (CNES)", à mão e todo mês), que tem a
internet que a sessão não tem. Incremental: guarda os arquivos já lidos (nome e tamanho) e só lê os novos ou mudados.

    python3 tools/odontoscan/sia.py [--inicio 2023-01] [--fim 2026-12]

Saída: app/dados/sia/unioeste.json e tools/odontoscan/dados/sia-log.txt.
"""
import argparse
import ftplib
import json
import os
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[2]
SAIDA = RAIZ / "app/dados/sia/unioeste.json"
LOGF = RAIZ / "tools/odontoscan/dados/sia-log.txt"
ESTADO = RAIZ / "tools/odontoscan/dados/sia-estado.json"  # o que já foi lido, com os agregados de cada arquivo
CNES = {"3523365": "Unioeste Odontologia", "6391915": "CEO III Unioeste"}
FTP, PASTA = "ftp.datasus.gov.br", "/dissemin/publicos/SIASUS/200801_/Dados"
LOG = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    LOG.append(s)


def descompactar(dbc, dbf):
    try:
        from pyreaddbc import dbc2dbf
        dbc2dbf(str(dbc), str(dbf))
        return
    except ImportError:
        pass
    import datasus_dbc
    datasus_dbc.decompress(str(dbc), str(dbf))


def ler_dbf(caminho, filtro_campo, valores, campos):
    """Lê um .dbf de registros fixos com numpy: devolve {campo: [str]} só das linhas com filtro_campo em valores."""
    with open(caminho, "rb") as f:
        cab = f.read(32)
        n = int.from_bytes(cab[4:8], "little")
        tam_cab = int.from_bytes(cab[8:10], "little")
        tam_reg = int.from_bytes(cab[10:12], "little")
        desc = {}
        pos = 1  # o 1º byte do registro é a marca de apagado
        while True:
            d = f.read(32)
            if not d or d[0] == 0x0D:
                break
            nome = d[:11].split(b"\0")[0].decode("latin-1").strip()
            tam = d[16]
            desc[nome] = (pos, tam)
            pos += tam
    arr = np.memmap(caminho, dtype=np.uint8, mode="r", offset=tam_cab, shape=(n, tam_reg))
    o, t = desc[filtro_campo]
    col = arr[:, o:o + t]
    sel = np.zeros(n, dtype=bool)
    for v in valores:
        alvo = np.frombuffer(v.ljust(t).encode("latin-1")[:t], dtype=np.uint8)
        sel |= (col == alvo).all(axis=1)
    sel &= arr[:, 0] != ord("*")  # apagados
    linhas = arr[sel]
    out = {}
    for c in campos:
        if c not in desc:
            out[c] = [""] * len(linhas)
            continue
        o, t = desc[c]
        out[c] = [bytes(x).decode("latin-1").strip() for x in linhas[:, o:o + t]]
    return out, list(desc), n


def num(s):
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return 0.0


def faixa(idade):
    try:
        i = int(idade)
    except ValueError:
        return ""
    for lim, nome in [(5, "0-4"), (10, "5-9"), (15, "10-14"), (20, "15-19"), (30, "20-29"), (40, "30-39"), (50, "40-49"), (60, "50-59")]:
        if i < lim:
            return nome
    return "60+" if i < 150 else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inicio", default="2023-01")
    ap.add_argument("--fim", default="2099-12")
    ap.add_argument("--refazer", action="store_true")
    a = ap.parse_args()
    ini, fim = a.inicio.replace("-", ""), a.fim.replace("-", "")
    velho = {}
    if ESTADO.exists() and not a.refazer:
        velho = json.loads(ESTADO.read_text())
    lidos = dict(velho.get("arquivos", {}))
    # agregados por arquivo, para poder trocar um arquivo refeito sem somar duas vezes
    por_arq = dict(velho.get("porArquivo", {}))

    ftp = ftplib.FTP(FTP, timeout=300)
    ftp.login()
    ftp.cwd(PASTA)
    nomes = []
    ftp.retrlines("NLST", nomes.append)
    alvos = []
    for nome in sorted(nomes):
        m = re.fullmatch(r"PAPR(\d\d)(\d\d)([a-z]?)\.dbc", nome, re.I)
        if not m:
            continue
        aamm = "20" + m.group(1) + m.group(2)
        if ini <= aamm <= fim:
            alvos.append(nome)
    log(f"{len(alvos)} arquivos PA do Paraná entre {a.inicio} e {a.fim}")
    mostrou = False
    for nome in alvos:
        try:
            tam = ftp.size(nome)
        except Exception:  # noqa: BLE001
            tam = None
        if nome in lidos and lidos[nome] == tam:
            continue
        t0 = time.time()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dbc, dbf = Path(tmp) / nome, Path(tmp) / (nome[:-4] + ".dbf")
                for tent in range(3):
                    try:
                        with open(dbc, "wb") as f:
                            ftp.retrbinary(f"RETR {nome}", f.write, blocksize=1 << 20)
                        break
                    except Exception as e:  # noqa: BLE001
                        log(f"  {nome}: falha no download ({e}), tentativa {tent + 1}")
                        time.sleep(20)
                        ftp = ftplib.FTP(FTP, timeout=300)
                        ftp.login()
                        ftp.cwd(PASTA)
                descompactar(dbc, dbf)
                campos = ["PA_CMP", "PA_MVM", "PA_CODUNI", "PA_PROC_ID", "PA_QTDPRO", "PA_QTDAPR", "PA_VALAPR", "PA_MUNPCN", "PA_SEXO", "PA_IDADE"]
                d, todos, n = ler_dbf(dbf, "PA_CODUNI", list(CNES), campos)
                if not mostrou:
                    mostrou = True
                    log("  campos do PA:", ", ".join(todos))
            proc, mun, perfil = {}, {}, {}
            for k in range(len(d["PA_CODUNI"])):
                cmp_, cnes, pid = d["PA_CMP"][k], d["PA_CODUNI"][k], d["PA_PROC_ID"][k]
                qp, qa, va = num(d["PA_QTDPRO"][k]), num(d["PA_QTDAPR"][k]), num(d["PA_VALAPR"][k])
                x = proc.setdefault(f"{cmp_}|{cnes}|{pid}", [0, 0, 0.0])
                x[0] += qp; x[1] += qa; x[2] += va
                if d["PA_MUNPCN"][k]:
                    kk = f"{cmp_}|{cnes}|{d['PA_MUNPCN'][k]}"
                    mun[kk] = mun.get(kk, 0) + qa
                fx = faixa(d["PA_IDADE"][k])
                sx = d["PA_SEXO"][k] if d["PA_SEXO"][k] in ("M", "F") else ""
                if fx or sx:
                    kk = f"{cmp_}|{cnes}|{sx}|{fx}"
                    perfil[kk] = perfil.get(kk, 0) + qa
            por_arq[nome] = {"proc": proc, "mun": mun, "perfil": perfil}
            lidos[nome] = tam
            log(f"  {nome}: {n} registros no PR, {len(d['PA_CODUNI'])} da UNIOESTE ({time.time() - t0:.0f} s)")
        except Exception as e:  # noqa: BLE001
            log(f"  {nome}: ERRO {e}")
            log(traceback.format_exc()[-1500:])
        # grava a cada arquivo, para não perder nada se o tempo acabar
        gravar(lidos, por_arq)
    ftp.quit()
    gravar(lidos, por_arq)


def gravar(lidos, por_arq):
    proc, mun, perfil = {}, {}, {}
    for ag in por_arq.values():
        for k, v in ag["proc"].items():
            x = proc.setdefault(k, [0, 0, 0.0])
            x[0] += v[0]; x[1] += v[1]; x[2] += v[2]
        for k, v in ag["mun"].items():
            mun[k] = mun.get(k, 0) + v
        for k, v in ag["perfil"].items():
            perfil[k] = perfil.get(k, 0) + v
    meses = sorted({k.split("|")[0] for k in proc})
    dados = {
        "fonte": "SIA/SUS (DATASUS), arquivos PA do Paraná; agregados por competência (PA_CMP)",
        "gerado": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "cnes": CNES,
        "meses": meses,
        # [competência AAAAMM, cnes, procedimento, apresentado, aprovado, valor aprovado]
        "procedimentos": sorted([[*k.split("|"), int(v[0]), int(v[1]), round(v[2], 2)] for k, v in proc.items()]),
        # [competência, cnes, município de residência (IBGE 6 dígitos), aprovado]
        "municipios": sorted([[*k.split("|"), int(v)] for k, v in mun.items()]),
        # [competência, cnes, sexo, faixa etária, aprovado] (só o BPA individualizado tem sexo e idade)
        "perfil": sorted([[*k.split("|"), int(v)] for k, v in perfil.items()]),
        "arquivos": len(lidos),
    }
    ESTADO.write_text(json.dumps({"arquivos": lidos, "porArquivo": por_arq}, separators=(",", ":")))
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    LOGF.write_text("\n".join(LOG) + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        log(traceback.format_exc())
        LOGF.write_text("\n".join(LOG) + "\n")
        sys.exit(1)

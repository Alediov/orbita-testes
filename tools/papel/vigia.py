"""O vigia dos agendamentos (22/11/2026): o agendamento do GitHub pula rodadas (o copy trading, de 2 em 2 h, rodou 4
vezes em 40 h; o robô do intervalo, de 15 em 15 min, nenhuma em 5 h). O robô do intervalo agora roda sem parar (um
laço de ~5h40 que se dispara de novo no fim) e, a cada volta, este vigia dispara pela API o workflow que estiver
atrasado e sem rodada na fila. Usa o `gh` do executor com o GITHUB_TOKEN automático (só `actions: write`)."""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request

HORA = 3600
# workflow: (atraso máximo em segundos desde a última rodada criada, entradas do disparo)
LIMITES = {
    "mercado.yml": (2 * HORA + 45 * 60, {}),
    "memes.yml": (10 * HORA, {}),
    "ideias.yml": (14 * HORA, {}),
    "evolucao.yml": (30 * HORA, {}),
    "even3.yml": (26 * HORA, {}),
}
APOSTAS_MAX = 80 * 60        # o papel só com as apostas: a cada hora
PAPEL_MAX = 7 * HORA         # a rodada inteira do papel: a cada 6 h (pela hora dos cofres no ramo papel)


def gh(*args):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip()[:300])
    return r.stdout


def repo():
    return os.environ.get("GITHUB_REPOSITORY") or "Alediov/orbita-testes"


def ultimas(wf):
    """[(criada em segundos, status)] das últimas rodadas do workflow."""
    out = json.loads(gh("run", "list", "-R", repo(), "-w", wf, "-L", "5", "--json", "createdAt,status"))
    xs = []
    for x in out:
        t = dt.datetime.fromisoformat(x["createdAt"].replace("Z", "+00:00")).timestamp()
        xs.append((t, x["status"]))
    return xs


def disparar(wf, entradas, motivo, log):
    args = ["workflow", "run", wf, "-R", repo(), "--ref", "main"]
    for k, v in entradas.items():
        args += ["-f", f"{k}={v}"]
    gh(*args)
    log(f"vigia: disparou {wf}{' ' + json.dumps(entradas) if entradas else ''} ({motivo})")


def na_fila(xs):
    return any(s in ("queued", "in_progress", "waiting", "pending", "requested") for _t, s in xs)


def agora_do_ramo(arquivo):
    """O `agora` (ms) de um arquivo do ramo papel, pelo raw do GitHub; None se não der."""
    try:
        url = f"https://raw.githubusercontent.com/{repo()}/papel/{arquivo}"
        with urllib.request.urlopen(url, timeout=20) as r:
            return int(json.loads(r.read().decode("utf-8")).get("agora") or 0) / 1000
    except Exception:  # noqa: BLE001
        return None


def main():
    def log(x):
        print(x)
    agora = dt.datetime.now(dt.timezone.utc).timestamp()
    for wf, (limite, entradas) in LIMITES.items():
        try:
            xs = ultimas(wf)
            if na_fila(xs):
                continue
            ult = max((t for t, _s in xs), default=0)
            if agora - ult > limite:
                disparar(wf, entradas, f"a última foi há {(agora - ult) / HORA:.1f} h", log)
        except Exception as e:  # noqa: BLE001
            log(f"vigia: {wf}: {e}")
    try:
        xs = ultimas("papel.yml")
        if not na_fila(xs):
            ult = max((t for t, _s in xs), default=0)
            cofres = agora_do_ramo("cofres.json")
            if cofres is not None and agora - cofres > PAPEL_MAX:
                disparar("papel.yml", {}, f"os cofres são de há {(agora - cofres) / HORA:.1f} h", log)
            elif agora - ult > APOSTAS_MAX:
                disparar("papel.yml", {"formas": "apostas"}, f"a última foi há {(agora - ult) / 60:.0f} min", log)
    except Exception as e:  # noqa: BLE001
        log(f"vigia: papel.yml: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Cliente HTTP pequeno das apostas no papel (tools/papel/apostas.py). Só biblioteca padrão, só leitura.

Três fontes gratuitas:

- football-data.co.uk: planilhas CSV com resultados e odds de fechamento e de antes do jogo (sem chave);
- OddsPapi v4 (https://api.oddspapi.io/v4): odds ao vivo e o histórico delas; plano GRATUITO com chave (sem cartão),
  ~250 pedidos por mês. A chave vem SÓ da variável de ambiente ODDSPAPI_KEY (o workflow passa o segredo do
  repositório): nunca vai para arquivo, log ou mensagem de erro (os erros citam só o caminho, sem a consulta);
- o placar público da ESPN (site.api.espn.com, sem chave), para conferir resultados.

`pedidos` conta todas as tentativas; `contagem` separa por tipo ("csv", "oddspapi", "espn"). Na OddsPapi cada
tentativa conta no limite do mês, por isso lá as novas tentativas são poucas.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

UA = "orbita-testes/1"
URL_ODDSPAPI = "https://api.oddspapi.io/v4"
REPETIR = (429, 500, 502, 503, 504)


class Erro(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def decodificar(dados: bytes) -> str:
    """As planilhas do football-data às vezes vêm em latin-1 (ou cp1252) e às vezes com BOM do UTF-8."""
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return dados.decode(cod)
        except UnicodeDecodeError:
            continue
    return dados.decode("latin-1", errors="replace")


class Cliente:
    def __init__(self, chave=None, tentativas=3, prazo=40, dormir=time.sleep, log=print):
        self.chave = chave or None  # NUNCA gravar nem mostrar
        self.tentativas, self.prazo, self.dormir, self.log = tentativas, prazo, dormir, log
        self.pedidos = 0
        self.contagem = Counter()

    def _limpar(self, texto):
        texto = str(texto)
        if self.chave:
            texto = texto.replace(self.chave, "***")
        return texto

    def _baixar(self, url, tipo, rotulo, tentativas=None):
        tentativas = tentativas or self.tentativas
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        for k in range(tentativas):
            self.pedidos += 1
            self.contagem[tipo] += 1
            try:
                with urllib.request.urlopen(req, timeout=self.prazo) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code in REPETIR and k < tentativas - 1:
                    s = min(60, 5 * 2 ** k)
                    self.log(f"  HTTP {e.code} em {rotulo}; espera {s}s")
                    self.dormir(s)
                    continue
                raise Erro(f"HTTP {e.code} em {rotulo}", e.code) from None
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                if k < tentativas - 1:
                    self.dormir(min(30, 3 * 2 ** k))
                    continue
                motivo = getattr(e, "reason", None) or type(e).__name__
                raise Erro(self._limpar(f"rede em {rotulo}: {motivo}")) from None
        raise Erro(f"sem resposta em {rotulo}")

    # ------------------------------------------------------------------ pedidos
    def texto(self, url, tipo="csv"):
        """Um arquivo de texto (as planilhas do football-data)."""
        return decodificar(self._baixar(url, tipo, url))

    def json_url(self, url, tipo="espn"):
        """JSON de uma URL pública sem chave (o placar da ESPN)."""
        rotulo = url.split("?")[0]
        try:
            return json.loads(self._baixar(url, tipo, rotulo).decode("utf-8", errors="replace"))
        except ValueError as e:
            raise Erro(f"JSON inválido em {rotulo}") from e

    def oddspapi(self, caminho, **params):
        """GET na OddsPapi v4 (`caminho` como "/fixtures"). Sem chave: Erro. Só 2 tentativas (cada uma gasta o mês)."""
        if not self.chave:
            raise Erro("falta a chave da OddsPapi")
        consulta = {k: v for k, v in params.items() if v is not None}
        consulta["apiKey"] = self.chave
        url = f"{URL_ODDSPAPI}{caminho}?{urllib.parse.urlencode(consulta)}"
        try:
            dados = self._baixar(url, "oddspapi", f"OddsPapi {caminho}", tentativas=2)
            return json.loads(dados.decode("utf-8", errors="replace"))
        except ValueError:
            raise Erro(f"JSON inválido em OddsPapi {caminho}") from None

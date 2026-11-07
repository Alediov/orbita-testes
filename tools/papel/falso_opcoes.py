"""Opções de MENTIRA (sem rede; semente fixa): a API pública da Deribit sobre os preços do mundo de mentira
(tools/mercado/falso.py), no formato das amostras do Teste de alcance (ver opcoes.py). Nada aqui é dado real.

- `get_volatility_index_data`: um DVOL que anda em regimes (40–75% no BTC, um pouco mais no ETH), de hora em hora;
- `get_book_summary_by_currency`: a cadeia de agora, vencimentos nas próximas 6 sextas e nas últimas sextas dos 2
  meses seguintes, strikes de 1.000 (BTC) e 50 (ETH) até ±40%, preços pela fórmula com a inclinação, compra/venda a
  ±3% em tiques de 0,0001 da moeda (sem oferta de compra quando arredonda para zero), na MOEDA como na Deribit;
- `get_index_price` e `get_delivery_prices` (o preço às 08h UTC de cada dia).
"""
from __future__ import annotations

import datetime as dt
import math
import random

import opcoes as O

HORA = 3_600_000
DIA = 86_400_000
NIVEL = {"BTC": 0.50, "ETH": 0.62}


class Falso:
    def preparar(self):
        self._dvol = {}
        r = random.Random(2207)
        t0 = (self.mundo_ini() // HORA) * HORA - 400 * DIA
        n = 470 * 24
        for m, nivel in NIVEL.items():
            xs, x, alvo = [], nivel, nivel
            for i in range(n):
                if i % (24 * 5) == 0:
                    alvo = nivel * r.choice([0.8, 0.9, 1.0, 1.0, 1.15, 1.4])
                x += 0.05 * (alvo - x) + r.gauss(0, 0.004)
                xs.append((t0 + i * HORA, max(0.2, x)))
            self._dvol[m] = dict(xs)

    def mundo_ini(self):
        import falso_mercado
        return falso_mercado.T0

    def _iv(self, m, t):
        return self._dvol[m].get((int(t) // HORA) * HORA, NIVEL[m])

    def _cadeia(self, m):
        t = self.agora
        S = self.mundo.px(m, t)
        base = self._iv(m, t)
        a = O.sexta_08(t)
        vencs = [a + k * 7 * DIA for k in range(1, 7)]
        d = dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc)
        for k in (1, 2):  # a última sexta deste mês e do seguinte (os mensais)
            ano, mes = d.year + (d.month + k - 1) // 12, (d.month + k - 1) % 12 + 1
            u = dt.datetime(ano, mes, 1, O.HORA_VENC, tzinfo=dt.timezone.utc) - dt.timedelta(days=1)
            while u.weekday() != 4:
                u -= dt.timedelta(days=1)
            vencs.append(int(u.timestamp() * 1000))
        passo = O.PASSO_STRIKE[m]
        centro = round(S / passo) * passo
        out = []
        for v in sorted(set(vencs)):
            if v <= t:
                continue
            T = (v - t) / O.ANO_MS
            fut = S * (1 + 0.04 * T)  # o futuro do vencimento, um pouco acima do índice
            for i in range(-int(0.4 * S / passo), int(0.4 * S / passo) + 1):
                K = centro + i * passo
                for tipo in ("put", "call"):
                    iv = O.iv_com_inclinacao(base, fut, K, T, tipo)
                    teo = O.bs(fut, K, T, iv, tipo) / S  # na moeda
                    bid = math.floor(teo * 0.97 / O.TIQUE) * O.TIQUE
                    ask = math.ceil(teo * 1.03 / O.TIQUE) * O.TIQUE
                    out.append({"instrument_name": O.nome_instrumento(m, v, K, tipo), "bid_price": round(bid, 4) or None,
                                "ask_price": round(max(ask, O.TIQUE), 4), "mark_price": round(teo, 8),
                                "mark_iv": round(iv * 100, 2), "underlying_price": round(fut, 2),
                                "underlying_index": f"{m}-futuro", "estimated_delivery_price": round(S, 2),
                                "base_currency": m, "quote_currency": m, "interest_rate": 0.0, "open_interest": 10.0})
        return out

    def deribit(self, metodo, **p):
        self._contar("deribit:" + metodo)
        if metodo == "get_book_summary_by_currency":
            return self._cadeia(p["currency"])
        if metodo == "get_index_price":
            m = p["index_name"].split("_")[0].upper()
            s = round(self.mundo.px(m, self.agora), 2)
            return {"estimated_delivery_price": s, "index_price": s}
        if metodo == "get_delivery_prices":
            m = p["index_name"].split("_")[0].upper()
            hoje8 = (self.agora // DIA) * DIA + O.HORA_VENC * HORA
            if hoje8 > self.agora:
                hoje8 -= DIA
            dados = []
            for k in range(int(p.get("count") or 10)):
                tk = hoje8 - k * DIA
                dados.append({"date": dt.datetime.fromtimestamp(tk / 1000, dt.timezone.utc).strftime("%Y-%m-%d"),
                              "delivery_price": round(self.mundo.px(m, tk), 2)})
            return {"data": dados, "records_total": 2658}
        if metodo == "get_volatility_index_data":
            m = p["currency"]
            a, b = int(p["start_timestamp"]), min(int(p["end_timestamp"]), self.agora)
            pts = [[h, round(v * 100, 2), round(v * 101, 2), round(v * 99, 2), round(v * 100, 2)]
                   for h, v in sorted(self._dvol[m].items()) if a <= h <= b][:1000]
            return {"data": pts, "continuation": None}
        raise O.rede.Erro(f"método de mentira desconhecido: {metodo}")

"""Even3: funções puras que leem o texto de uma página de evento (sem rede; testadas em teste_even3.py).

Critérios (os mesmos da tarefa que o Alediov rodava à mão no navegador):
  - data de início = a data pedida (amanhã, fuso America/Sao_Paulo);
  - formato ONLINE;
  - inscrições abertas: botão "REALIZAR INSCRIÇÃO" e pelo menos um ingresso vigente (fora "Não disponível",
    "Encerrado", "Esgotado" e "Em breve");
  - certificado PARA O PARTICIPANTE dito com todas as letras ("com certificado", "certificado de participação",
    "certificado de 20 horas"…), nunca "instrutora certificada", "certificação ISO" e afins.
E marca os de Odontologia, com o motivo (onde e qual termo), tomando cuidado com os falsos positivos ("oral" de
"apresentação oral", "implantação", "acidente", dentistas só numa lista de profissões do público-alvo…).
"""
from __future__ import annotations

import re
import unicodedata

MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8, "set": 9, "out": 10,
         "nov": 11, "dez": 12}


def sem_acento(t: str) -> str:
    t = unicodedata.normalize("NFD", t or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def norm(t: str) -> str:
    """Minúsculas, sem acentos, espaços simples (os índices NÃO batem com o original: use só para procurar)."""
    return re.sub(r"[ \t ]+", " ", sem_acento(t).lower())


def frases(texto: str) -> list[str]:
    """Quebra em frases/linhas curtas (para devolver o trecho que prova algo)."""
    partes = []
    for linha in (texto or "").splitlines():
        linha = linha.strip()
        if not linha:
            continue
        for p in re.split(r"(?<=[.!?;])\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ0-9•\-–])", linha):
            p = p.strip(" •-–\t")
            if p:
                partes.append(p)
    return partes


def curto(t: str, n: int = 220) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------- certificado

_CERT_SIM = [
    r"com (emissao de )?certificad",
    r"certificad[oa]s? (digita(l|is) |simbolico |online |gratuito |eletronico )?(de|da|para) (participa|ouvinte|presenca|conclusao|frequencia)",
    r"(obtencao de|com|direito a|emissao de|emite|emitira) certificac",
    r"certificac\w* (de |da )?(participac|ouvinte|presenca|conclusao)|certificac\w* (com|de) (carga horaria|\d{1,3} ?(h|horas))|"
    r"certificac\w* condicionad",
    r"certificad[oa]s? (digita(l|is) )?de \d{1,3} ?(h\b|hs\b|hrs?\b|horas?)",
    r"certificad[oa]s? (digita(l|is) )?(com|de|da) (carga horaria|\d{1,3} ?(h|horas))",
    r"certificad[oa]s? (sera|serao|vai ser|vao ser)\b",
    # "é"/"são" (sem acento o "é" vira "e": "Certificados e Materiais" não pode contar)
    r"certificad[oa]s? (e|sao) (emitid|enviad|disponibilizad|gratuit|digita|online|garantid|entregue|concedid|valid|liberad|"
    r"inclus|para todos)",
    r"(emissao|emite|emitira|emitirao|emitimos|emitido|emitidos) (de |o |os |um )?certificad",
    r"certificad[oa]s? (emitid|disponibilizad|enviad|liberad|gratuit|incluso|inclusos|online|on-line|digita(l|is)"
    r"(?! (e-?cpf|e-?cnpj|a1|a3|icp)))",
    r"(recebe|receber|recebera|receberao|recebem|ganha|ganhara|garanta|garante|direito (a|ao)|tera direito|terao direito|"
    r"acesso (a|ao)|faz jus) (o |um |seu |ao |a |os |seus )?certificad",
    r"certificad[oa]s? (aos|para os|para todos|a todos|ao|para o|para) (os )?(participante|inscrit|ouvinte|presente|"
    r"aluno|estudante)",
    r"(vale|valem|conta|contam|validos? como) (como )?(certificad|horas complementares|atividades? complementar)",
    r"certificad[oa]s? (de|com) horas complementares",
    r"^certificad[oa]s?\s*[:\-–]\s*(sim|\d|gratuit|incluso|digital)",
]
_CERT_NAO = [
    r"(instrutor|instrutora|professor|professora|palestrante|profissional|terapeuta|coach|consultor|consultora|"
    r"especialista|personal|treinador|treinadora|nutricionista|psicologa|psicologo|empresa|instituicao|clinica|"
    r"laboratorio|produto|organico|organica) (internacionalmente |e |ja )?certificad",
    r"certificacao (iso|internacional|profissional|pmp|ona|lgpd|organica|ambiental|de qualidade)",
    r"certificad[oa]s? (pela|pelo|pelas|pelos|internacionalmente|em (yoga|coaching|pnl|terapia))",
    r"(e-?cpf|e-?cnpj|icp-?brasil|certificado digital a[13]|assinatura (com|por) certificado)",
    r"(nao|sem) (havera |ha |tera |emite |emitira |emissao de |direito a )?certificad",
    r"nao (sera|serao|e|sao) (emitid|fornecid|disponibilizad)[oa]s? certificad",
    r"certificad[oa]s? (nao|so para|apenas para|somente para) (sera|serao|palestrante|organiza|apresentador|autor|"
    r"monitor)",
]
_RE_SIM = [re.compile(p) for p in _CERT_SIM]
_RE_NAO = [re.compile(p) for p in _CERT_NAO]
_RE_HORAS = [
    re.compile(r"certifica(?:do|da|dos|das|cao|coes)\b[^.\n|]{0,40}?\b(\d{1,3}(?:[.,]\d)?) ?(?:\([a-z ]+\) ?)?(?:h\b|hs\b|hrs?\b|horas?\b)"),
    re.compile(r"\b(\d{1,3}(?:[.,]\d)?) ?(?:h|hs|horas?)\b(?: \w+){0,3} (?:de )?certifica(?:do|cao)"),
    re.compile(r"carga horaria(?: total)?(?: do certificado)?(?: de| :|:|=| e de| sera de)? ?(\d{1,3}(?:[.,]\d)?) ?"
               r"(?:h\b|hs\b|hrs?\b|horas?\b)"),
    re.compile(r"\b(\d{1,3}(?:[.,]\d)?) ?(?:h|horas?) (?:complementares|de atividades? complementar)"),
]


def certificado(texto: str) -> dict | None:
    """{trecho, horas} se o texto diz que o PARTICIPANTE recebe certificado; None se não diz (ou nega)."""
    achado = None
    negado = None
    for f in frases(texto):
        n = norm(f)
        if "certific" not in n:
            continue
        if any(r.search(n) for r in _RE_NAO):
            # uma frase que nega certificado para o participante derruba tudo; "instrutora certificada" só não conta
            if re.search(r"(nao|sem) (havera |ha |tera |emite |emitira |emissao de |direito a )?certificad|"
                         r"nao (sera|serao) (emitid|fornecid|disponibilizad)", n) and "palestrante" not in n:
                negado = f
            continue
        if any(r.search(n) for r in _RE_SIM):
            if not achado:
                achado = f
    if negado and not achado:
        return None
    if not achado:
        return None
    return {"trecho": curto(achado), "horas": horas_certificado(texto, achado)}


def horas_certificado(texto: str, trecho: str = "") -> float | None:
    """Horas do certificado: primeiro no próprio trecho, depois "carga horária" ou "N horas complementares"."""
    for alvo in (norm(trecho), norm(texto)):
        if not alvo:
            continue
        for r in _RE_HORAS:
            for m in r.finditer(alvo):
                # "das 19h às 21h" não é carga horária
                antes = alvo[max(0, m.start(1) - 6): m.start(1)]
                depois = alvo[m.end(): m.end() + 6]
                if re.search(r"(das|as|a partir das|ate as|inicio)\s*$", antes) or re.match(r"\s*(as|a)\s+\d", depois):
                    continue
                if re.match(r"\d{1,2}:\d", alvo[m.start(1):m.start(1) + 5]):
                    continue
                v = float(m.group(1).replace(",", "."))
                if 0 < v <= 500:
                    return int(v) if v == int(v) else v
    return None


# ---------------------------------------------------------------- inscrições

_FECHADO = re.compile(r"\b(nao disponivel|encerrad[oa]s?|esgotad[oa]s?|em breve|inscricoes (fechadas|encerradas)|"
                      r"vagas esgotadas|indisponivel)\b")


def inscricoes(texto: str) -> dict:
    """{abertas, botao, ingressos: [{nome, valor, situacao}], motivo}.

    O Even3 mostra os ingressos em linhas (nome, valor e, quando não dá para comprar, a situação) e o botão
    "REALIZAR INSCRIÇÃO". Sem o botão = fechado; com o botão e todos os ingressos marcados como fechados = fechado.
    Sem lista de ingressos legível, vale o botão.
    """
    n = norm(texto)
    botao = bool(re.search(r"realizar inscricao|realizar minha inscricao|inscreva-se agora", n))
    ing = ingressos(texto)
    vigentes = [i for i in ing if i["situacao"] == "vigente"]
    if not botao:
        return {"abertas": False, "botao": False, "ingressos": ing, "motivo": "sem o botão REALIZAR INSCRIÇÃO"}
    if ing and not vigentes:
        sit = sorted({i["situacao"] for i in ing})
        return {"abertas": False, "botao": True, "ingressos": ing, "motivo": "ingressos: " + ", ".join(sit)}
    if not ing and re.search(r"inscricoes (encerradas|fechadas|esgotadas)|evento encerrado", n):
        return {"abertas": False, "botao": True, "ingressos": ing, "motivo": "inscrições encerradas"}
    return {"abertas": True, "botao": True, "ingressos": ing, "motivo": ""}


_RE_VALOR = re.compile(r"(gratuit[oa]|gr[aá]tis|free|r\$ ?\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", re.I)


def ingressos(texto: str) -> list[dict]:
    """Lê o bloco de ingressos: do título "Ingressos"/"Inscrições" até o botão de inscrição (ou 40 linhas)."""
    linhas = [l.strip() for l in (texto or "").splitlines() if l.strip()]
    ln = [norm(l) for l in linhas]
    ini = None
    for i, l in enumerate(ln):
        if re.fullmatch(r"(ingressos?|inscricoes|inscricao|valores|investimento|categorias de inscricao)( e valores)?:?", l):
            ini = i + 1
    if ini is None:
        return []
    fim = len(linhas)
    for j in range(ini, min(len(linhas), ini + 60)):
        if re.search(r"realizar (minha )?inscricao", ln[j]):
            fim = j
            break
    else:
        fim = min(len(linhas), ini + 40)
    bloco = list(range(ini, fim))
    res = []
    atual = None
    for j in bloco:
        l, o = ln[j], linhas[j]
        val = _RE_VALOR.search(o)
        fech = _FECHADO.search(l)
        if val:
            v = val.group(0)
            v = "Gratuito" if norm(v) in ("gratuito", "gratuita", "gratis", "free") else v.upper().replace("R$", "R$ ").replace("  ", " ")
            if atual and atual.get("valor") is None:
                atual["valor"] = v
            else:
                nome = re.sub(_RE_VALOR, "", o).strip(" -–:|") or (atual["nome"] if atual and atual.get("valor") is None else "Ingresso")
                atual = {"nome": curto(nome, 80), "valor": v, "situacao": "vigente"}
                res.append(atual)
            if fech and atual:
                atual["situacao"] = situacao(fech.group(0))
            continue
        if fech:
            if atual:
                atual["situacao"] = situacao(fech.group(0))
            continue
        # linha de texto: nome do próximo ingresso (se for curta e não for data/descrição)
        if len(o) <= 80 and not re.search(r"\d{2}/\d{2}|\bate\b|lote|vagas? ?:|^(valor|preco|ingresso|tipo)$", l):
            atual = {"nome": curto(o, 80), "valor": None, "situacao": "vigente"}
            res.append(atual)
    # nomes soltos sem valor nem situação não são ingressos
    return [r for r in res if r["valor"] is not None or r["situacao"] != "vigente"]


def situacao(t: str) -> str:
    t = norm(t)
    if "breve" in t:
        return "em breve"
    if "esgot" in t:
        return "esgotado"
    if "encerr" in t or "fechad" in t:
        return "encerrado"
    return "não disponível"


def preco(ing: list[dict]) -> dict:
    """{texto, gratuito} pelos ingressos vigentes (o mais barato)."""
    vig = [i for i in ing if i["situacao"] == "vigente" and i.get("valor")]
    if not vig:
        return {"texto": None, "gratuito": None}
    if any(i["valor"] == "Gratuito" for i in vig):
        pagos = [i for i in vig if i["valor"] != "Gratuito"]
        return {"texto": "Gratuito" + (" (há ingressos pagos)" if pagos else ""), "gratuito": True}
    vals = sorted(vig, key=lambda i: valor_num(i["valor"]))
    t = vals[0]["valor"] + (" a " + vals[-1]["valor"] if valor_num(vals[-1]["valor"]) > valor_num(vals[0]["valor"]) else "")
    return {"texto": t, "gratuito": False}


def valor_num(v: str) -> float:
    m = re.search(r"(\d{1,3}(?:\.\d{3})*)(?:,(\d{2}))?", v or "")
    if not m:
        return 0.0
    return float(m.group(1).replace(".", "") + "." + (m.group(2) or "00"))


# ---------------------------------------------------------------- data, horário, formato, plataforma

def datas_e_horas(texto: str) -> list[tuple[str, str | None]]:
    """Todas as (AAAA-MM-DD, HH:MM|None) do texto, na ordem: "04/11/2026 19:00", "04 nov 2026 às 19h",
    "4 de novembro de 2026, 19h30"."""
    n = norm(texto)
    achados = []
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{4})(?:[^\d\n]{0,12}?(\d{1,2})[:h](\d{2})?)?", n):
        d, mes, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        h = f"{int(m.group(4)):02d}:{m.group(5) or '00'}" if m.group(4) and int(m.group(4)) < 24 else None
        if 1 <= d <= 31 and 1 <= mes <= 12:
            achados.append((m.start(), f"{a:04d}-{mes:02d}-{d:02d}", h))
    for m in re.finditer(r"\b(\d{1,2})(?: de)? (jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)[a-z]*\.?(?: de)? ?(\d{4})?"
                         r"(?:[^\d\n]{0,14}?(\d{1,2})[:h](\d{2})?)?", n):
        d, mes = int(m.group(1)), MESES[m.group(2)]
        a = int(m.group(3)) if m.group(3) else 0
        h = f"{int(m.group(4)):02d}:{m.group(5) or '00'}" if m.group(4) and int(m.group(4)) < 24 else None
        if 1 <= d <= 31:
            achados.append((m.start(), f"{a:04d}-{mes:02d}-{d:02d}", h))
    achados.sort()
    return [(d, h) for _, d, h in achados]


def periodo(texto: str, data: str) -> dict:
    """{inicio: "HH:MM"|None, fim, dataInicio, dataFim, comeca_no_dia: bool, inclui_dia: bool}.

    Procura primeiro um bloco "Data"/"Quando" (o cabeçalho do Even3); senão as primeiras datas do texto.
    """
    linhas = (texto or "").splitlines()
    cab = "\n".join(linhas[:60])
    ds = datas_e_horas(cab) or datas_e_horas(texto)
    ano = data[:4]
    ds = [((d if not d.startswith("0000") else ano + d[4:]), h) for d, h in ds]
    if not ds:
        return {"inicio": None, "fim": None, "dataInicio": None, "dataFim": None, "comeca_no_dia": False,
                "inclui_dia": False}
    ini_d, ini_h = ds[0]
    fim_d, fim_h = ini_d, None
    # o fim é a data seguinte do cabeçalho ("até 04/11/2026 21:00") ou um "às 21h" logo depois do início
    if len(ds) > 1 and ds[1][0] >= ini_d:
        fim_d, fim_h = ds[1]
    if fim_h is None and ini_h:
        # "19h30 às 21h", "19:00 - 21:00": a primeira hora depois da de início
        nc = norm(cab)
        h0, m0 = int(ini_h[:2]), ini_h[3:]
        pos = next((x.end() for x in re.finditer(r"\b0?%d[:h]%s" % (h0, m0 if m0 != "00" else "(?:00)?"), nc)), -1)
        if pos >= 0:
            m = re.match(r"\s*(?:h\s*)?(?:ate|as|a|-|–)\s*(?:as\s*)?(\d{1,2})(?:[:h](\d{2})?)", nc[pos:])
            if m and int(m.group(1)) < 24 and f"{int(m.group(1)):02d}:{m.group(2) or '00'}" > ini_h:
                fim_h = f"{int(m.group(1)):02d}:{m.group(2) or '00'}"
    return {"inicio": ini_h, "fim": fim_h, "dataInicio": ini_d, "dataFim": fim_d, "comeca_no_dia": ini_d == data,
            "inclui_dia": ini_d <= data <= fim_d}


_RE_CAB = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})(?:\s*[–-]\s*(\d{2})/(\d{2})/(\d{4}))?(?:\s*-\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2}))?"
                     r"\s*(?:GMT|$)", re.M)


def cabecalho(texto: str) -> dict | None:
    """A linha de data do cabeçalho das páginas do Even3: " 04/11/2026 – 05/11/2026 - 18:00 - 21:30 GMT-3"."""
    m = _RE_CAB.search("\n".join((texto or "").splitlines()[:12]))
    if not m:
        return None
    g = m.groups()
    ini = f"{g[2]}-{g[1]}-{g[0]}"
    fim = f"{g[5]}-{g[4]}-{g[3]}" if g[3] else ini
    z = lambda h: f"{int(h.split(':')[0]):02d}:{h.split(':')[1]}" if h else None
    return {"dataInicio": ini, "dataFim": fim, "inicio": z(g[6]), "fim": z(g[7])}


def formato(texto: str) -> str:
    """"online", "presencial", "hibrido" ou "?" (pelo que o Even3 escreve no cabeçalho)."""
    n = norm("\n".join((texto or "").splitlines()[:80]))
    if "este e um evento online" in n:
        return "online"
    on = bool(re.search(r"\b(evento )?(online|on-line|virtual|remoto|ao vivo pela internet|transmissao online)\b", n))
    pres = bool(re.search(r"\bevento presencial\b|\bpresencial\b", n))
    hib = bool(re.search(r"\bhibrido\b", n))
    if hib or (on and pres):
        return "hibrido"
    if on:
        return "online"
    if pres:
        return "presencial"
    return "?"


PLATAFORMAS = [
    ("YouTube", r"youtube|you tube|\byt\b"),
    ("Google Meet", r"google meet|\bmeet\b|meet\.google"),
    ("Zoom", r"\bzoom\b"),
    ("Microsoft Teams", r"\bteams\b"),
    ("StreamYard", r"streamyard"),
    ("Instagram", r"instagram|\binsta\b"),
    ("Facebook", r"facebook"),
    ("Twitch", r"twitch"),
    ("Discord", r"discord"),
    ("Jitsi", r"jitsi"),
    ("Webex", r"webex"),
    ("RNP (Conferência Web)", r"conferenciaweb|conferencia web|\brnp\b"),
    ("Even3 (área do participante)", r"(plataforma|transmissao|transmitido|ambiente|sala) (virtual )?(do |da |pelo |pela |no |na )?even3|"
                                     r"area do participante|even3 play|ao vivo (no|pelo) even3"),
    ("WhatsApp", r"whatsapp"),
    ("Moodle", r"moodle"),
]


def plataforma(texto: str) -> str | None:
    n = norm(texto)
    achou = [nome for nome, p in PLATAFORMAS if re.search(p, n)]
    # redes sociais só com cara de transmissão: "Compartilhar no Facebook" e "ENTRAR EM CONTATO · INSTAGRAM" (o
    # rodapé do organizador) não são plataforma
    for nome in ("Facebook", "WhatsApp", "Instagram"):
        if nome in achou and not re.search(r"(transmi\w*|ao vivo|\blives?\b|\blink\b|sala|grupo)[^.\n]{0,60}" + nome.lower(), n):
            achou.remove(nome)
    return ", ".join(achou) if achou else None


# ---------------------------------------------------------------- Odontologia

# (rótulo, padrão, forte?) — fortes bastam sozinhos no título/resumo; fracos precisam de companhia
TERMOS_ODONTO = [
    ("odontologia", r"odonto\w*", True),
    ("dentista", r"\b(cirurgi[aoõ]e?s?[- ])?dentistas?\b", True),
    ("dental/dentário", r"\b(dental|dentais|dentari[oa]s?|dentes?|dentina|dentic\w+)\b", True),
    ("bucal", r"\bbuca(l|is)\b|\bbucomaxil\w*|\bbuco[- ]?\w+", True),
    ("oral", r"\b(saude|cavidade|patologia|medicina|cirurgia|mucosa|higiene|lesao|lesoes|cancer|reabilitacao|"
             r"radiologia|microbiota|manifestac\w+|doencas?|biologia|implantodontia|estomatologia) orai?s?\b|"
             r"\borais? e maxilo|\boral (health|medicine|surgery|pathology)\b", True),
    ("periodontia", r"\bperiodont\w*|\bperi-?implant\w*", True),
    ("endodontia", r"\bendodont\w*", True),
    ("ortodontia", r"\bortodont\w*|ortopedia funcional dos maxilares", True),
    ("implantodontia", r"\bimplantodont\w*|\bimplantes? (dentari|osseointegr|oss|imediato|zigomatic)\w*", True),
    ("prótese dentária", r"\bprotese (dentaria|total|parcial|sobre implantes?|fixa|removivel)|\bprotesista|\bprotetic\w+", True),
    ("estomatologia", r"\bestomatolog\w*", True),
    ("CTBMF", r"\bctbmf\b|bucomaxilofacial|\bcirurgia (e traumatologia )?buco|maxilofacial", True),
    ("saúde bucal", r"saude bucal", True),
    ("DTM/ATM", r"\bdtm\b|temporomandibular|\bdisfunc\w+ temporo", True),
    ("harmonização orofacial", r"harmonizac\w+ orofacial|\bhof\b|\borofacia(l|is)\b", True),
    ("cárie", r"\bcaries?\b", True),
    ("gengiva", r"\bgengiv\w*", True),
    ("dentística", r"\bdentistica\b|\bclareamento dent\w*|\bfacetas? (de porcelana|em resina|dent)\w*|"
                   r"\bresinas? compostas?\b", True),
    ("odontopediatria", r"\bodontopediatr\w*|\bodontogeriatr\w*|\bodontolegal\b", True),
    ("bruxismo", r"\bbruxismo\b", True),
    ("halitose", r"\bhalitose\b", True),
    ("maloclusão", r"\bm[aá]-?oclus\w+|\boclusao\b", True),
    ("anestesia local odontológica", r"anestesia (local )?(odontolog|em odontolog)\w*|bloqueio do (nervo )?alveolar", True),
    ("CRO", r"\bcro-?[a-z]{2}\b|conselho (regional|federal) de odontologia|\bcfo\b", False),
    ("fluoretação", r"\bfluoretac\w+|\bfluorose\b", False),
    ("radiologia odontológica", r"\bradiografias? (panoramica|periapica|interproximal)\w*|tomografia cone beam|\bcbct\b", False),
]
_RE_TERMOS = [(r, re.compile(p), forte) for r, p, forte in TERMOS_ODONTO]
# expressões que contêm um termo mas não são Odontologia
_FALSOS = re.compile(
    r"apresentac\w+ oral|comunicac\w+ oral|prova oral|expressao oral|linguagem oral|tradic\w+ oral|historia oral|"
    r"via oral|uso oral|lingua oral|producao oral|exposicao oral|comunicacao (escrita e )?oral|"
    r"implantac\w+|acidente|dente de leao|dentes? de serra|dente de alho|\bdentes? do (pente|engrenagem)|"
    r"servico de atendimento oral|arguic\w+ oral")
# listas de profissões: "médicos, enfermeiros, dentistas e fisioterapeutas" (público amplo, não é de Odontologia)
_PROFISSOES = re.compile(r"medic|enfermeir|fisioterapeut|psicolog|nutricionist|farmaceutic|fonoaudiolog|"
                         r"biomedic|veterinari|educador|assistente social|terapeuta ocupacional|profissionais da saude")


def odontologia(titulo: str, resumo: str, texto: str) -> dict:
    """{sim, nivel: "forte"|"fraco"|None, motivos: [..], porque: "..."}.

    forte: termo de Odontologia no título ou no resumo, ou ≥ 2 termos diferentes no corpo (fora de lista de
    profissões); fraco: só uma menção no corpo, ou dentistas no meio de uma lista de profissões (o app não destaca).
    """
    achados = {"título": [], "resumo": [], "texto": []}
    profissoes = 0
    mencoes = 0  # quantas vezes os termos fortes aparecem no corpo
    for onde, t in (("título", titulo), ("resumo", resumo), ("texto", texto)):
        n = _FALSOS.sub(" ", norm(t))
        for rot, r, forte in _RE_TERMOS:
            m = r.search(n)
            if not m:
                continue
            if onde == "texto" and rot == "dentista":
                viz = n[max(0, m.start() - 90): m.end() + 90]
                if len(set(_PROFISSOES.findall(viz))) >= 1 and not re.search(r"odonto", viz):
                    profissoes += 1
                    continue
            achados[onde].append((rot, m.group(0).strip(), forte))
            if onde == "texto" and forte:
                mencoes += len(r.findall(n))
    tit = [a for a in achados["título"] if a[2]]
    res = [a for a in achados["resumo"] if a[2]]
    corpo = {a[0] for a in achados["texto"]}
    if "saúde bucal" in corpo:  # "bucal" é o mesmo achado de "saúde bucal"
        corpo.discard("bucal")
    corpo_fortes = {a[0] for a in achados["texto"] if a[2]} & corpo
    motivos = []
    for onde in ("título", "resumo", "texto"):
        vistos = set()
        for rot, termo, _ in achados[onde]:
            if rot in vistos:
                continue
            vistos.add(rot)
            motivos.append(f"{onde}: “{termo}” ({rot})")
    if tit or res:
        onde = "no título" if tit else "no resumo"
        rot = max(tit or res, key=lambda a: len(a[1]))[0]  # o mais específico ("saúde bucal" e não "bucal")
        return {"sim": True, "nivel": "forte", "motivos": motivos[:6], "porque": f"{rot} {onde}"}
    if corpo_fortes and (len(corpo) >= 2 or mencoes >= 3):
        return {"sim": True, "nivel": "forte", "motivos": motivos[:6],
                "porque": "o texto fala de " + ", ".join(sorted(corpo)[:3])}
    if corpo or profissoes:
        porque = ("cita dentistas numa lista de profissões" if profissoes and not corpo
                  else "uma menção só no texto: " + ", ".join(sorted(corpo)))
        return {"sim": False, "nivel": "fraco", "motivos": motivos[:6] or ["texto: dentistas entre outras profissões"],
                "porque": porque}
    return {"sim": False, "nivel": None, "motivos": [], "porque": ""}


# ---------------------------------------------------------------- JSON-LD (schema.org Event) das páginas do Even3

_RE_LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
MODOS = {"online": "on", "offline": "off", "mixed": "mix"}


def jsonld_evento(html: str) -> dict | None:
    """O primeiro objeto @type Event dos <script type="application/ld+json"> (ou None)."""
    import json
    for m in _RE_LD.finditer(html or ""):
        try:
            d = json.loads(m.group(1).strip())
        except Exception:
            continue
        for o in (d if isinstance(d, list) else [d]):
            if isinstance(o, dict) and "Event" in str(o.get("@type", "")):
                return o
    return None


def resumo_ld(ld: dict | None) -> dict:
    """{d: AAAA-MM-DD|None, f: AAAA-MM-DD|None, m: on|off|mix|?, nome} (o Even3 às vezes escreve "2026-11-19T :00"; a hora
    não presta, a data sim)."""
    if not ld:
        return {"d": None, "f": None, "m": "?", "nome": "", "hi": None, "hf": None}
    data = lambda v: (re.match(r"(\d{4}-\d{2}-\d{2})", str(v or "")) or [None, None])[1]
    modo = norm(str(ld.get("eventAttendanceMode") or ""))
    m = next((v for k, v in MODOS.items() if k in modo), "?")
    hora = lambda v: (re.findall(r"(\d{2}:\d{2}):\d{2}", str(v or "")) or [None])[-1]  # "2026-11-04T00:0021:30:00.000" → 21:30
    return {"d": data(ld.get("startDate")), "f": data(ld.get("endDate")), "m": m, "nome": str(ld.get("name") or "")[:200],
            "hi": hora(ld.get("startDate")), "hf": hora(ld.get("endDate"))}


def _quando(v: str | None):
    import datetime as dt
    v = str(v or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(v[:19] if "T" in v else v, fmt)
        except ValueError:
            continue
    return None


def ofertas(ld: dict | None, agora) -> list[dict]:
    """Os ingressos do JSON-LD no formato de `ingressos()`: {nome, valor, situacao} (vigente, esgotado, encerrado, em breve,
    não disponível), pela `availability` e pela janela availabilityStarts/Ends (hora de Brasília, `agora` sem fuso)."""
    res = []
    for o in (ld or {}).get("offers") or []:
        if not isinstance(o, dict):
            continue
        av = norm(str(o.get("availability") or "")).rsplit("/", 1)[-1]
        ini, fim = _quando(o.get("availabilityStarts")), _quando(o.get("availabilityEnds"))
        try:
            preco = float(str(o.get("price") or "0").replace(",", "."))
        except ValueError:
            preco = 0.0
        valor = "Gratuito" if preco <= 0 else "R$ " + f"{preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        # a janela primeiro: o Even3 marca SoldOut também o ingresso "Em breve" e o que já fechou
        if ini and agora < ini:
            sit = "em breve"
        elif fim and agora > fim:
            sit = "encerrado"
        elif av in ("soldout", "outofstock"):
            sit = "não disponível"
        elif av in ("preorder", "presale"):
            sit = "em breve"
        elif av in ("discontinued",):
            sit = "encerrado"
        elif av in ("instock", "limitedavailability", "onlineonly", "instoreonly", ""):
            sit = "vigente"
        else:
            sit = "não disponível"
        res.append({"nome": curto(str(o.get("name") or "Ingresso"), 80), "valor": valor, "situacao": sit})
    return res


# ---------------------------------------------------------------- tudo junto

def id_do_link(url: str) -> str:
    m = re.search(r"-(\d{4,})/?(?:[?#].*)?$", url or "") or re.search(r"/(\d{4,})/?(?:[?#].*)?$", url or "")
    if m:
        return "e3-" + m.group(1)
    slug = re.sub(r"^https?://[^/]+/", "", url or "").strip("/").split("?")[0]
    return "e3-" + re.sub(r"[^a-z0-9]+", "-", norm(slug))[:60]


def analisar(evento: dict, texto: str, data: str, ld: dict | None = None, agora=None) -> dict:
    """Junta tudo para um evento: devolve {ok, motivo, ...campos do JSON}.

    `evento`: {titulo, url, resumo, url_final?}; `texto`: document.body.innerText da página do evento; `ld`: o JSON-LD
    (schema.org Event) da página, que manda na data, no formato e nos ingressos quando existe; `agora`: datetime sem
    fuso em Brasília (padrão: agora).
    """
    import datetime as dt
    if agora is None:
        agora = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=3)).replace(tzinfo=None)
    rl = resumo_ld(ld)
    titulo = (evento.get("titulo") or rl["nome"] or "").strip()
    resumo = (evento.get("resumo") or "").strip()
    per = periodo(texto, data)
    cab = cabecalho(texto)
    if cab:  # o cabeçalho do Even3 manda (datas e, quando tem, as horas)
        per = {**cab, "inicio": cab["inicio"], "fim": cab["fim"]}
    elif rl["d"] and per["dataInicio"] != rl["d"]:  # a hora do texto era de outra data
        per = {**per, "inicio": None, "fim": None}
    if rl["d"]:  # a data do JSON-LD é a do cadastro
        fim_d = rl["f"] or rl["d"]
        per.update({"dataInicio": rl["d"], "dataFim": fim_d})
        if not per.get("inicio") and rl["hi"] and rl["hi"] != "00:00":
            per["inicio"] = rl["hi"]
        if not per.get("fim") and rl["hf"] and rl["hf"] != "00:00" and (not per.get("inicio") or rl["hf"] > per["inicio"]):
            per["fim"] = rl["hf"]
    if per.get("fim") and per.get("inicio") and (per["fim"] == per["inicio"] or
                                                 (per["fim"] < per["inicio"] and per.get("dataFim") in (None, per.get("dataInicio")))):
        per["fim"] = None  # "19:00 - 19:00": o fim não foi informado
    per["comeca_no_dia"] = per.get("dataInicio") == data
    per["inclui_dia"] = bool(per.get("dataInicio")) and per["dataInicio"] <= data <= (per.get("dataFim") or per["dataInicio"])
    form = {"on": "online", "off": "presencial", "mix": "hibrido"}.get(rl["m"]) or formato(texto)
    ins = inscricoes(texto)
    ofs = ofertas(ld, agora)
    if ofs:  # os ingressos do JSON-LD valem mais que os lidos do texto
        vig = [o for o in ofs if o["situacao"] == "vigente"]
        ins = {**ins, "ingressos": ofs, "abertas": ins["botao"] and bool(vig),
               "motivo": "" if ins["botao"] and vig else ("sem o botão REALIZAR INSCRIÇÃO" if not ins["botao"] else
                                                          "ingressos: " + ", ".join(sorted({o["situacao"] for o in ofs})))}
    cert = certificado(texto)
    pr = preco(ins["ingressos"])
    od = odontologia(titulo, resumo, texto)
    item = {
        "id": id_do_link(evento.get("url") or ""),
        "nome": titulo,
        "resumo": curto(resumo or primeira_descricao(texto), 300),
        "url": evento.get("url"),
        "urlFinal": evento.get("url_final") if evento.get("url_final") != evento.get("url") else None,
        "data": per["dataInicio"],
        "dataFim": per["dataFim"] if per["dataFim"] != per["dataInicio"] else None,
        "inicio": per["inicio"],
        "fim": per["fim"],
        "formato": form,
        "preco": pr["texto"],
        "gratuito": pr["gratuito"],
        "ingressos": [i for i in ins["ingressos"]][:8],
        "plataforma": plataforma(texto),
        "certificado": cert,
        "odonto": od,
    }
    motivo = ""
    if per["dataInicio"] and not per["comeca_no_dia"]:
        motivo = "começa em " + per["dataInicio"] if per["dataInicio"] > data else "começou antes (" + per["dataInicio"] + ")"
    elif form in ("presencial", "hibrido"):
        motivo = "formato " + form
    elif not ins["abertas"]:
        motivo = "inscrições fechadas (" + ins["motivo"] + ")"
    elif not cert:
        motivo = "sem certificado para o participante"
    item["ok"] = not motivo
    item["motivo"] = motivo
    item["avisos"] = [a for a in (
        "data não achada na página (vale o filtro do Even3)" if not per["dataInicio"] else "",
        "formato não dito na página (vale o filtro online)" if form == "?" else "",
    ) if a]
    return item


def primeira_descricao(texto: str) -> str:
    for f in frases(texto):
        if len(f) > 80 and not re.search(r"cookies|politica de privacidade|even3", norm(f)):
            return f
    return ""

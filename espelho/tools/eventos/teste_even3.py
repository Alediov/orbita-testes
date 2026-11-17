"""Testes do classificador do Even3 (sem rede): python3 tools/eventos/teste_even3.py"""
import datetime as dt
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import classificar as C  # noqa: E402

falhas = 0


def ok(cond, msg):
    global falhas
    if not cond:
        falhas += 1
        print("FALHOU:", msg)


AGORA = dt.datetime(2026, 11, 3, 17, 0)
DIA = "2026-11-04"

# ---------- certificado: o participante recebe (sim) × certificação de outra coisa (não)
SIM = [
    ("Evento gratuito e com certificado.", None),
    ("Todos os inscritos receberão certificado de participação.", None),
    ("Certificado de 20 horas para quem assistir às duas noites.", 20),
    ("Haverá emissão de certificado digital com carga horária de 4h.", 4),
    ("Os certificados serão disponibilizados na área do participante.", None),
    ("Certificado: sim (2 horas)", 2),
    ("O evento vale como horas complementares, com certificado de 3h.", 3),
    ("Ao final, os participantes terão direito a certificado.", None),
]
NAO = [
    "Com a instrutora certificada internacionalmente em Yoga.",
    "Empresa com certificação ISO 9001.",
    "Aprenda a assinar documentos com certificado digital A1 e e-CPF.",
    "Este evento não emitirá certificado.",
    "Profissional certificado pela ABRAFIT.",
    "Palestra sobre o novo sistema da clínica.",
]
for t, h in SIM:
    r = C.certificado("Webinar\n" + t)
    ok(r is not None, f"certificado não visto em: {t}")
    ok(r is None or r["horas"] == h, f"horas {r and r['horas']} ≠ {h} em: {t}")
for t in NAO:
    ok(C.certificado("Webinar\n" + t) is None, f"certificado falso em: {t}")
ok(C.horas_certificado("Das 19h às 21h. Com certificado.") is None, "19h às 21h não é carga horária")
# frases das páginas reais (rodada de 03/11/2026)
for t, h in [("Os ouvintes receberão certificado de 30 (trinta) horas/atividades", 30),
             ("a participação como monitores e a obtenção de certificação com carga horária complementar.", None),
             ("Certificação condicionada ao cumprimento dos critérios de participação definidos pela organização.", None),
             ("Ao concluir a série, você poderá receber um certificado simbólico de conclusão.", None),
             ("🎓 Certificado de 12h", 12), ("Certificado: 3 horas", 3),
             ("De 04 a 06 de novembro de 2026 | 100% on-line | Inscrição gratuita | Certificação de 30 horas", 30)]:
    r = C.certificado("Evento\n" + t + "\nMinicursos de 40 h no 2º dia.")
    ok(r is not None and r["horas"] == h, f"página real: {t} → {r}")
ok(C.certificado("Evento\nOrientações sobre conhecimentos, habilidades e certificações.") is None, "certificações profissionais")
ok(C.certificado("Evento\n📃 Certificados e Materiais Didáticos") is None, "um título “Certificados e Materiais” não prova nada")
ok(C.certificado("Evento\nO certificado é emitido em até 7 dias.") is not None, "o certificado é emitido")
ok(C.horas_certificado("Carga horária: 8 horas. Com certificado.") == 8, "carga horária: 8 horas")

# ---------- Odontologia: o que é e o que só parece
od = C.odontologia("Webinar de Periodontia Clínica", "", "")
ok(od["sim"] and od["nivel"] == "forte" and "periodontia" in od["porque"], f"periodontia no título: {od}")
od = C.odontologia("Jornada Acadêmica", "Saúde bucal na atenção básica", "")
ok(od["sim"] and od["porque"] == "saúde bucal no resumo", f"saúde bucal no resumo: {od}")
od = C.odontologia("Simpósio de DTM e dor orofacial", "", "")
ok(od["sim"], "DTM no título")
od = C.odontologia("Curso de Harmonização Orofacial", "", "")
ok(od["sim"], "HOF no título")
od = C.odontologia("I Congresso de Cirurgia e Traumatologia Bucomaxilofacial", "", "")
ok(od["sim"], "CTBMF")
for titulo, texto in [
    ("Oficina de apresentação oral de trabalhos", "Como fazer uma boa comunicação oral."),
    ("Implantação de sistemas ERP", "A implantação do sistema na empresa."),
    ("Prevenção de acidentes de trabalho", "Acidente com dentes de serra."),
    ("Farmacologia: medicamentos por via oral", ""),
    ("História oral e memória", ""),
]:
    od = C.odontologia(titulo, "", texto)
    ok(not od["sim"], f"falso positivo: {titulo} → {od}")
od = C.odontologia("Congresso de Saúde da Família", "", "Público: médicos, enfermeiros, dentistas e fisioterapeutas.")
ok(not od["sim"] and od["nivel"] == "fraco", f"dentistas numa lista de profissões: {od}")
od = C.odontologia("Encontro de Saúde Coletiva", "", "Mesa sobre fluorose e saúde bucal. A cárie na infância e o acesso ao dentista.")
ok(od["sim"], f"vários termos no texto: {od}")

od = C.odontologia("Feira de Saúde", "", "Estandes de nutrição, vacinação e saúde bucal.")
ok(not od["sim"] and od["nivel"] == "fraco", f"uma menção só de saúde bucal no texto: {od}")
od = C.odontologia("Webinário - Triagem de risco na UBS", "", "Triagem de risco em saúde bucal. O cuidado em saúde bucal na escola. Indicadores de saúde bucal.")
ok(od["sim"], f"saúde bucal repetida no texto: {od}")
p = C.analisar({"titulo": "x", "url": "u"}, "LOGIN\nX\n 09/11/2026 – 12/11/2026 - 19:00 - 19:00 GMT-3\n Este é um evento online", "2026-11-09")
ok(p["inicio"] == "19:00" and p["fim"] is None, f"19:00 - 19:00: {p['inicio']} {p['fim']}")

# ---------- JSON-LD: data, modo e ofertas
HTML = '''<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"Event",
"name":"Webinar de Periodontia","startDate":"2026-11-04T :00.000-03:00","endDate":"2026-11-04T00:00 :00.000-03:00",
"eventAttendanceMode":"https://schema.org/OnlineEventAttendanceMode","offers":[
{"@type":"Offer","price":"0.00","availability":"http://schema.org/InStock","name":"Estudante","availabilityStarts":"2026-10-01T00:00","availabilityEnds":"2026-11-04T18:00"},
{"@type":"Offer","price":"30.00","availability":"http://schema.org/SoldOut","name":"Profissional"},
{"@type":"Offer","price":"1500.5","availability":"http://schema.org/InStock","name":"Lote 2","availabilityStarts":"2026-11-10T00:00"}]}
</script></head></html>'''
ld = C.jsonld_evento(HTML)
rl = C.resumo_ld(ld)
ok(rl == {"d": "2026-11-04", "f": "2026-11-04", "m": "on", "nome": "Webinar de Periodontia", "hi": None, "hf": None}, f"resumo do JSON-LD: {rl}")
# as horas, quando o Even3 as escreve ("2026-11-04T00:0021:30:00.000-03:00" é o fim às 21h30)
rl2 = C.resumo_ld({"@type": "Event", "startDate": "2026-11-04T18:30:00.000-03:00", "endDate": "2026-11-04T00:0021:30:00.000-03:00"})
ok((rl2["hi"], rl2["hf"]) == ("18:30", "21:30"), f"horas do JSON-LD: {rl2}")
ofs = C.ofertas(ld, AGORA)
ok([o["situacao"] for o in ofs] == ["vigente", "não disponível", "em breve"], f"situações: {ofs}")
ok([o["valor"] for o in ofs] == ["Gratuito", "R$ 30,00", "R$ 1.500,50"], f"valores: {ofs}")
ok(C.ofertas(ld, dt.datetime(2026, 11, 4, 19, 0))[0]["situacao"] == "encerrado", "a janela do ingresso fechou")
ok(C.resumo_ld(C.jsonld_evento('<script type="application/ld+json">{"@type":"Event","startDate":"2026-11-04T19:00",'
                                '"eventAttendanceMode":"https://schema.org/MixedEventAttendanceMode"}</script>'))["m"] == "mix", "híbrido")
ok(C.jsonld_evento("<html>sem nada</html>") is None, "sem JSON-LD")

# ---------- inscrições pelo texto
TXT = "Ingressos\nEstudante\nGratuito\nProfissional\nR$ 30,00\nEsgotado\nREALIZAR INSCRIÇÃO"
i = C.inscricoes(TXT)
ok(i["abertas"] and len(i["ingressos"]) == 2, f"inscrições abertas: {i}")
i = C.inscricoes("Ingressos\nEstudante\nGratuito\nEncerrado\nREALIZAR INSCRIÇÃO")
ok(not i["abertas"] and "encerrado" in i["motivo"], f"só ingresso encerrado: {i}")
i = C.inscricoes("Ingressos\nEstudante\nGratuito\n")
ok(not i["abertas"] and "botão" in i["motivo"], f"sem o botão: {i}")
ok(C.preco(C.inscricoes(TXT)["ingressos"]) == {"texto": "Gratuito", "gratuito": True}, "preço: gratuito")

# ---------- data e horário pelo texto
p = C.periodo("Webinar\n04/11/2026 19:00 até 04/11/2026 21:00\nOnline", DIA)
ok(p["inicio"] == "19:00" and p["fim"] == "21:00" and p["comeca_no_dia"], f"período dd/mm: {p}")
p = C.periodo("Webinar\n4 de novembro de 2026, 19h30 às 21h\nOnline", DIA)
ok(p["inicio"] == "19:30" and p["fim"] == "21:00", f"período por extenso: {p}")
p = C.periodo("Curso\n02/11/2026 08:00 até 06/11/2026 18:00", DIA)
ok(not p["comeca_no_dia"] and p["inclui_dia"], f"começou antes: {p}")

# ---------- o cabeçalho das páginas do Even3
ok(C.cabecalho("LOGIN\nWebinar\n 04/11/2026 - 18:30 - 21:30 GMT-3\n Este é um evento online") ==
   {"dataInicio": "2026-11-04", "dataFim": "2026-11-04", "inicio": "18:30", "fim": "21:30"}, "cabeçalho de um dia")
ok(C.cabecalho("LOGIN\nCurso\n 04/11/2026 – 05/11/2026 - 18:00 - 21:30 GMT-3") ==
   {"dataInicio": "2026-11-04", "dataFim": "2026-11-05", "inicio": "18:00", "fim": "21:30"}, "cabeçalho de dois dias")
ok(C.cabecalho("LOGIN\nSimpósio\n 04/11/2026 – 06/11/2026\n Este é um evento online") ==
   {"dataInicio": "2026-11-04", "dataFim": "2026-11-06", "inicio": None, "fim": None}, "cabeçalho sem horas")
ok(C.formato("LOGIN\nX\n 04/11/2026\n Este é um evento online") == "online", "evento online pelo cabeçalho")
ok(C.inscricoes("Inscrições\nEstudantes\nGrátis\naté 04/11/2026\nREALIZAR INSCRIÇÃO")["ingressos"][0]["valor"] == "Gratuito", "Grátis")

# ---------- plataforma (os botões de compartilhar não contam)
ok(C.plataforma("Transmissão ao vivo pelo YouTube. Compartilhar no Facebook") == "YouTube", "YouTube sem o Facebook do compartilhar")
ok(C.plataforma("Organizado por\nSecretaria\n ENTRAR EM CONTATO  INSTAGRAM") is None, "o Instagram do rodapé não é plataforma")
ok(C.plataforma("Live no Instagram @evento às 19h") == "Instagram", "live no Instagram")
ok("Google Meet" in (C.plataforma("O link do Google Meet será enviado por e-mail.") or ""), "Meet")

# ---------- tudo junto
TEXTO = """Webinar de Periodontia
04/11/2026 19:00 até 04/11/2026 21:00
Evento Online
Sobre o evento
Transmissão pelo YouTube. Os participantes receberão certificado de 2 horas.
REALIZAR INSCRIÇÃO"""
item = C.analisar({"titulo": "", "url": "https://www.even3.com.br/webinar-perio-805123/", "resumo": ""}, TEXTO, DIA, ld, AGORA)
ok(item["ok"], f"evento bom recusado: {item['motivo']}")
ok(item["id"] == "e3-805123" and item["nome"] == "Webinar de Periodontia", f"id e nome: {item['id']} {item['nome']}")
ok(item["inicio"] == "19:00" and item["fim"] == "21:00" and item["formato"] == "online", f"horário/formato: {item}")
ok(item["preco"].startswith("Gratuito") and item["plataforma"] == "YouTube" and item["certificado"]["horas"] == 2, f"campos: {item}")
ok(item["odonto"]["sim"], "Odontologia pelo nome do JSON-LD")
ld_off = dict(ld, eventAttendanceMode="https://schema.org/OfflineEventAttendanceMode")
ok(C.analisar({"titulo": "x", "url": "u"}, TEXTO, DIA, ld_off, AGORA)["motivo"] == "formato presencial", "presencial pelo JSON-LD")
sem_cert = TEXTO.replace(" Os participantes receberão certificado de 2 horas.", "")
ok(C.analisar({"titulo": "x", "url": "u"}, sem_cert, DIA, ld, AGORA)["motivo"] == "sem certificado para o participante", "sem certificado")
ld_esg = dict(ld, offers=[dict(o, availability="http://schema.org/SoldOut") for o in ld["offers"]])
ok(C.analisar({"titulo": "x", "url": "u"}, TEXTO, DIA, ld_esg, AGORA)["motivo"].startswith("inscrições fechadas"), "esgotado pelo JSON-LD")
ok(C.id_do_link("https://www.even3.com.br/ICONAFROEDU-764690/") == "e3-764690", "id pelo número")
ok(C.id_do_link("https://eventos.foar.unesp.br/jornada/") == "e3-jornada", "id sem número")

print("ok" if not falhas else f"{falhas} falha(s)")
sys.exit(1 if falhas else 0)

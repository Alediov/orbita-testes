"""A genética das versões que evoluem (tirada do evolucao.py em 16/11/2026, sem mudar nada, para o copy trading usar a
mesma: tools/mercado/evolucao_copia.py). Pura: sem rede, sem os Robôs.

Uma espécie é `{ id, genes: [gene] }`; um gene é `{ k, tipo: "num" | "int" | "bool" | "op", min, max, passo, opcoes,
neutro, so }` ("so": o gene só vale quando os outros têm esses valores; senão fica no `neutro`, para duas versões
iguais terem a mesma chave).
"""
from __future__ import annotations

import math

MUT_FILHA = 0.15

# os nomes das versões (um prenome e os sobrenomes da família; ver `Especie.batizar`)
NOMES = (
    "Ana Bento Clara Davi Elisa Fábio Gabi Heitor Iara João Kaio Lara Miguel Nina Otávio Paula Quim Rosa Sávio "
    "Tânia Ulisses Vera Wagner Xênia Yuri Zélia Alice Bruno Cecília Diego Estela Felipe Giovana Hugo Ísis Júlio "
    "Kátia Lucas Marina Nelson Olga Pedro Raquel Samuel Tereza Úrsula Vítor Wanda Yara Zeca Amanda Breno Carla "
    "Dante Flora Gustavo Helena Ícaro Joana Leandro Lívia Mateus Noemi Orlando Priscila Rafael Sofia Tiago "
    "Valéria Wesley Yasmin Zaqueu Aurora Benício Celina Dalila Enzo Fernanda Gael Heloísa Igor Júlia Lauro "
    "Maitê Nicolas Odete Renata Sílvio Talita Vicente Wilma Ágata Baltazar Cíntia Diogo Elaine Frederico Glória "
    "Irene Leonel Adriana Afonso Alana Alberto Alícia Álvaro Amélia André Anita Antônio Ariel Artur Augusto "
    "Bárbara Beatriz Bernardo Bianca Caio Camila Carlos Carolina Cássio Catarina César Cláudio Cristina Daniel "
    "Débora Denise Dirceu Dora Douglas Edgar Eduardo Elza Emanuel Érica Ernesto Eva Fabrício Fátima Flávio "
    "Francisco Gabriel Germano Gilberto Gisele Graça Guilherme Hélio Henrique Hilda Horácio Inês Isaac Isabel "
    "Ivan Jaime Janaína Jorge José Juliano Jussara Laís Laura Leila Leonardo Letícia Lia Lorena Luana Luciano "
    "Luís Luíza Magda Manuela Marcelo Márcia Marcos Mariana Mário Marta Maurício Mauro Melissa Milena Moisés "
    "Mônica Murilo Nádia Natália Nestor Norma Olívia Osvaldo Pâmela Patrícia Paulo Pietra Rebeca Regina "
    "Reinaldo Ricardo Rita Roberto Rodrigo Rogério Ronaldo Rosana Rúbia Rui Sabrina Sandra Sara Saulo Sebastião "
    "Sérgio Simone Sônia Suzana Tales Tatiana Teodoro Thaís Tomás Túlio Valentina Vanessa Vinícius Violeta "
    "Vitória Viviane Walter Zilda Abel Adélia Aline Amaro Ângela Anselmo Aparecida Arnaldo Benedita Berenice "
    "Bráulio Cacilda Celso Cora Dário Dulce Edite Elias Estêvão Eunice Fausto Felícia Firmino Gaspar Hermínia "
    "Iolanda Jacinto Joaquim Josué Lázaro Lídia Lourenço Madalena Matilde Nazaré Otília Plínio Quitéria "
    "Raimundo Rômulo Salomé Serafim Tadeu Tarsila Ubirajara Valdir Zulmira"
    " Adriano Alessandra Benjamim Betina Caetana Conrado Damião Dandara Eliane Emília Fabiana Gilda Guido Ingrid Jandira Jonas Kelly Lino Luna Marlene Nilo Otto Pilar Ramiro Selma Tobias Vânia Zoraide Aurélio Bela"
).split()
SOBRENOMES = (
    "Ferraz Lima Souza Silva Santos Oliveira Pereira Costa Almeida Ribeiro Carvalho Gomes Martins Rocha Barbosa "
    "Moreira Cardoso Teixeira Correia Fernandes Araújo Azevedo Barros Batista Borges Braga Brandão Brito Bueno "
    "Cabral Caldeira Camargo Campos Castro Cavalcanti Chaves Coelho Cordeiro Cunha Dias Duarte Esteves Farias "
    "Figueiredo Fonseca Fontes Freitas Furtado Garcia Godoy Guimarães Lacerda Leite Lopes Macedo Machado Maia "
    "Marques Matos Medeiros Meireles Melo Mendes Miranda Monteiro Morais Moura Nascimento Neves Nogueira Nunes "
    "Pacheco Paiva Peixoto Pimentel Pinheiro Pires Prado Queiroz Ramos Rangel Rezende Rios Sales Sampaio "
    "Siqueira Soares Tavares Toledo Torres Valadares Vargas Vasconcelos Viana Vieira Xavier Abreu Aguiar "
    "Albuquerque Alencar Amaral Andrade Antunes Aragão Assis Bastos Bezerra Bittencourt Calado Carneiro "
    "Casimiro Coutinho Damasceno Dantas Dutra Falcão Feitosa Fialho Franco Galvão Gouveia Guedes Guerra Holanda "
    "Jardim Lemos Linhares Lobo Louzada Luz Magalhães Malta Marinho Mesquita Muniz Navarro Negrão Novaes "
    "Ornelas Padilha Paes Paranhos Passos Pedrosa Pontes Portela Quintana Rabelo Resende Sá Salgado Saraiva "
    "Seixas Serra Simões Tenório Trindade Uchoa Valente Veloso Ventura Veríssimo Vidal Vilela Zanetti Arruda "
    "Baptista Barreto Bandeira Bragança Caetano Calixto Capistrano Cerqueira Cidade Colares Cortez Drummond "
    "Espíndola Estrela Fagundes Faria Gadelha Gusmão Horta Junqueira Lago Leal Madureira Maranhão Mascarenhas "
    "Montenegro Nóbrega Pessoa Quaresma Rosário Sardinha Taveira Varela"
    " Alves Amorim Castilho Diniz Lins Motta Peçanha Rolim Sobral"
).split()


def ativo(g, genes):
    """O gene vale com estes genes? `so` = {gene: valor} ou {gene: [valores]} (desde 25/11/2026: um gene que vale para
    mais de um tipo, como as partes do DCA semanal e do DCA na queda)."""
    return all(genes.get(k) in v if isinstance(v, list) else genes.get(k) == v for k, v in (g.get("so") or {}).items())


def _snap(g, x):
    lo, hi, p = g["min"], g["max"], g["passo"]
    x = min(hi, max(lo, x))
    x = lo + round((x - lo) / p) * p
    x = min(hi, max(lo, x))
    return int(round(x)) if g["tipo"] == "int" else round(x, 6)


def reparar(esp, genes):
    """Põe cada gene no domínio, os inativos no neutro e as regras da espécie (média lenta ≥ 2 × a rápida)."""
    out = {}
    for g in esp["genes"]:
        v = genes.get(g["k"], g["neutro"])
        if g["tipo"] in ("num", "int"):
            v = _snap(g, float(v))
        elif g["tipo"] == "bool":
            v = bool(v)
        elif v not in g["opcoes"]:
            v = g["neutro"]
        out[g["k"]] = v
    for g in esp["genes"]:
        if not ativo(g, out):
            out[g["k"]] = g["neutro"]
    if esp["id"] == "tendencia" and out["lenta"] < 2 * out["rapida"]:
        # a lenta sobe até o 1º valor da grade com pelo menos o dobro da rápida (72 h × 2 = 144 h cabe nos 200 h)
        gl = next(g for g in esp["genes"] if g["k"] == "lenta")
        out["lenta"] = min(gl["max"], gl["min"] + math.ceil((2 * out["rapida"] - gl["min"]) / gl["passo"]) * gl["passo"])
    if esp["id"] == "indicadores" and out.get("regra") == "mmalvo":
        # a média lenta fica pelo menos 4 h acima da rápida; a média com alvo sempre tem stop (1% sem o gene)
        gl = next(g for g in esp["genes"] if g["k"] == "lenta")
        if out["lenta"] < out["rapida"] + 4:
            out["lenta"] = _snap(gl, out["rapida"] + 4)
        if not out.get("stop"):
            out["stop"] = 0.01
    return out


def chave(genes):
    return "|".join(f"{k}={genes[k]}" for k in sorted(genes))


def sortear(rng, esp):
    genes = {}
    for g in esp["genes"]:
        if g["tipo"] in ("num", "int"):
            genes[g["k"]] = _snap(g, rng.uniform(g["min"], g["max"]))
        elif g["tipo"] == "bool":
            genes[g["k"]] = rng.random() < 0.5
        else:
            genes[g["k"]] = rng.choice(g["opcoes"])
    return reparar(esp, genes)


def _novo_valor(rng, g, v):
    if g["tipo"] in ("num", "int"):
        x = _snap(g, float(v) + rng.gauss(0, 0.2 * (g["max"] - g["min"])))
        if x == v:  # o sorteio caiu no mesmo degrau: um passo para um lado (ou para o outro, na borda)
            d = rng.choice((-1, 1)) * g["passo"]
            x = _snap(g, float(v) + d)
            if x == v:
                x = _snap(g, float(v) - d)
        return x
    if g["tipo"] == "bool":
        return not v
    outras = [o for o in g["opcoes"] if o != v]
    return rng.choice(outras) if outras else v


def mutar(rng, esp, genes, origem, n=1):
    """Muda `n` genes ativos (sorteados). Devolve (genes, origem, os genes mudados)."""
    antes = {g["k"]: ativo(g, genes) for g in esp["genes"]}
    genes, origem = dict(genes), dict(origem)
    mudados = []
    for _ in range(n):
        ativos = [g for g in esp["genes"] if ativo(g, genes) and g["k"] not in mudados]
        if not ativos:
            break
        g = rng.choice(ativos)
        genes[g["k"]] = _novo_valor(rng, g, genes[g["k"]])
        origem[g["k"]] = "mut"
        mudados.append(g["k"])
    novos = reparar(esp, genes)
    for g in esp["genes"]:
        k = g["k"]
        # mudou pela regra da espécie, ou passou a valer porque o gene de que depende mudou (o mercado, a saída)
        if (novos[k] != genes[k] or (ativo(g, novos) and not antes[k])) and k not in mudados:
            origem[k] = "mut"
    return novos, origem, mudados


def cruzar(rng, esp, pai, mae, mut=MUT_FILHA):
    """Cada gene vem do pai ou da mãe (sorteado); com a chance `mut`, um gene muda. Filha igual a um dos dois muda um
    gene. Devolve (genes, origem)."""
    genes, origem = {}, {}
    for g in esp["genes"]:
        k = g["k"]
        de = "pai" if rng.random() < 0.5 else "mae"
        genes[k] = (pai if de == "pai" else mae)["genes"][k]
        origem[k] = de
    bruto, genes = genes, reparar(esp, genes)
    for g in esp["genes"]:  # um gene ativo que a regra da espécie mudou (a média lenta) conta como mutação
        if genes[g["k"]] != bruto[g["k"]] and ativo(g, genes):
            origem[g["k"]] = "mut"
    if rng.random() < mut or chave(genes) in (chave(pai["genes"]), chave(mae["genes"])):
        genes, origem, _ = mutar(rng, esp, genes, origem)
    return genes, origem


def romano(n):
    """2 → "II", 14 → "XIV" (o 2º, o 3º… com o mesmo nome)."""
    out = ""
    for v, r in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
                 (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= v:
            out += r
            n -= v
    return out


# ====================================================================== notas

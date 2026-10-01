"""Confere no banco os valores literais da consulta (títulos, nomes, categorias).

Valor inexistente não gera erro nem aviso no Neo4j: `{titulo: 'Frieren'}` só faz a consulta
voltar vazia ou contar zero. Aqui o valor é procurado e, se não existir, a mensagem de erro
traz os valores parecidos para o modelo corrigir (ex.: 'Sousou no Frieren').
"""
import re
from dataclasses import dataclass

from analytics.lint import strip_strings, variables
from analytics.schema import MAX_CATEGORICAL

STRING = r"'((?:[^'\\]|\\.)*)'|\"((?:[^\"\\]|\\.)*)\""
NODE_MAP = re.compile(r"\(\s*(\w*)\s*:\s*(\w+)\s*\{")
REL_MAP = re.compile(r"\[\s*\w*\s*:\s*(\w+)[^\]{|]*\{")
MAP_ENTRY = re.compile(rf"(\w+)\s*:\s*(?:{STRING})")
EQUALS = re.compile(rf"\b(\w+)\.(\w+)\s*=\s*(?:{STRING})")
IN_LIST = re.compile(r"\b(\w+)\.(\w+)\s+IN\s+\[([^\]]*)\]", re.IGNORECASE)
STRING_ONLY = re.compile(STRING)
MAX_SUGGESTIONS = 5


@dataclass(frozen=True)
class Literal:
    kind: str  # "node" ou "rel"
    owner: str  # label ou tipo da relação
    prop: str
    value: str


def _value(match, first_group):
    raw = match.group(first_group) if match.group(first_group) is not None else match.group(first_group + 1)
    return raw.replace("\\'", "'").replace('\\"', '"')


def _map_body(text, start):
    """Conteúdo de um mapa `{...}` a partir da chave de abertura, pulando strings."""
    i, depth = start, 0
    while i < len(text):
        ch = text[i]
        if ch in "'\"":
            end = STRING_ONLY.match(text, i)
            i = end.end() if end else i + 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    return text[start + 1:]


def extract_literals(cypher):
    """Igualdades com string: mapas em nós/relações, `x.prop = '...'` e `x.prop IN [...]`."""
    node_vars, rel_vars = variables(strip_strings(cypher))
    found = []

    for m in NODE_MAP.finditer(cypher):
        for e in MAP_ENTRY.finditer(_map_body(cypher, m.end() - 1)):
            found.append((m.start(), Literal("node", m.group(2), e.group(1), _value(e, 2))))
    for m in REL_MAP.finditer(cypher):
        for e in MAP_ENTRY.finditer(_map_body(cypher, m.end() - 1)):
            found.append((m.start(), Literal("rel", m.group(1), e.group(1), _value(e, 2))))

    def owner(var):
        if var in node_vars:
            return "node", node_vars[var]
        if var in rel_vars:
            return "rel", rel_vars[var]
        return None

    for m in EQUALS.finditer(cypher):
        if o := owner(m.group(1)):
            found.append((m.start(), Literal(*o, m.group(2), _value(m, 3))))
    for m in IN_LIST.finditer(cypher):
        if o := owner(m.group(1)):
            for s in STRING_ONLY.finditer(m.group(3)):
                found.append((m.start(), Literal(*o, m.group(2), _value(s, 1))))

    unique = []
    for _, lit in sorted(found, key=lambda x: x[0]):
        if lit not in unique:
            unique.append(lit)
    return unique


def check_values(session, cypher, schema):
    problems = []
    for lit in extract_literals(cypher):
        props = (schema.node_props if lit.kind == "node" else schema.rel_props).get(lit.owner)
        if props is None or lit.prop not in props:
            continue  # label ou propriedade inexistente: o lint e o EXPLAIN já reclamam
        match = (f"MATCH (n:`{lit.owner}`)" if lit.kind == "node"
                 else f"MATCH ()-[n:`{lit.owner}`]->()")
        exists = session.run(f"{match} WHERE n.`{lit.prop}` = $v RETURN count(n) > 0 AS ok",
                             v=lit.value).single()["ok"]
        if exists:
            continue
        where = f"{lit.owner}.{lit.prop} = '{lit.value}' não existe no banco"
        if suggestions := _suggest(session, match, lit):
            problems.append(f"{where}; valores parecidos: {', '.join(repr(s) for s in suggestions)}")
        else:
            problems.append(f"{where}; confira a grafia")
    return problems


def _suggest(session, match, lit):
    distinct = session.run(
        f"{match} WHERE n.`{lit.prop}` IS NOT NULL "
        f"WITH DISTINCT n.`{lit.prop}` AS v LIMIT {MAX_CATEGORICAL + 1} RETURN v ORDER BY v"
    ).value()
    if len(distinct) <= MAX_CATEGORICAL:
        return distinct

    # Texto livre (títulos, nomes): o valor inteiro contido, senão qualquer palavra dele.
    # Para títulos, procura também no título em inglês; os mais populares vêm primeiro.
    fields = [f"n.`{lit.prop}`"] + (["n.titulo_en"] if lit.prop == "titulo" else [])
    words = [w.lower() for w in re.findall(r"\w{3,}", lit.value)]
    for terms in ([lit.value.lower()], words):
        if not terms:
            continue
        cond = " OR ".join(f"toLower(coalesce({f}, '')) CONTAINS t" for f in fields)
        found = session.run(
            f"{match} WHERE any(t IN $terms WHERE {cond}) "
            f"RETURN DISTINCT n.`{lit.prop}` AS v, coalesce(n.membros, 0) AS pop "
            f"ORDER BY pop DESC LIMIT {MAX_SUGGESTIONS}",
            terms=terms,
        ).value("v")
        if found:
            return found
    return []

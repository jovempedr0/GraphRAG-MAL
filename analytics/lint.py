"""Checagens contra o schema que o EXPLAIN não faz.

O EXPLAIN só reclama de label, relação ou propriedade que não existem em lugar nenhum do banco.
Os erros silenciosos são outros: seta invertida (a consulta roda e volta vazia) e propriedade
que existe, mas em outro lugar (`o.votos` em vez de `r.votos`, que devolve nulos), e divisão
entre contagens, que no Cypher é divisão inteira (2 / 5 = 0) e zera proporções sem erro.
"""
import re

# Relações gravadas num sentido só, mas sem direção de significado (ver CONVENTIONS).
UNDIRECTED = {"RECOMMENDS"}

STRING_PATTERN = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"")
NODE_PATTERN = re.compile(r"\(([^()]*)\)")
REL_BETWEEN = re.compile(r"^\s*(<)?-\s*(?:\[([^\]]*)\])?\s*-(>)?\s*$")
NODE_VAR_LABEL = re.compile(r"\(\s*(\w+)\s*:\s*(\w+)")
REL_VAR_TYPE = re.compile(r"\[\s*(\w+)\s*:\s*(\w+)\s*[\]*{\s]")
VAR_LABEL = re.compile(r"^\s*(\w+)?\s*(?::\s*(\w+))?")
REL_TYPES = re.compile(r":\s*([\w|:]+)")
PROPERTY_ACCESS = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\.([A-Za-z_]\w*)\b(?!\s*\()")
INTEGER_CALL = re.compile(r"\b(?:size|count|length)\s*\(|\bCOUNT\s*\{", re.IGNORECASE)
INT = "__int__"
INT_ALIAS = re.compile(rf"{INT}\s+AS\s+(\w+)", re.IGNORECASE)
DIVISION = re.compile(r"(?<![\w.])(\w+)\s*/\s*(\w+)(?![\w.(])")


def strip_strings(cypher):
    return STRING_PATTERN.sub("''", cypher)


def fix_undirected(cypher):
    """Tira a seta de relações sem direção de significado: `-[:RECOMMENDS]->` vira `-[:RECOMMENDS]-`."""
    types = "|".join(UNDIRECTED)
    pattern = re.compile(rf"<?-\[([^\]|]*:\s*(?:{types})\b[^\]|]*)\]->?")
    return pattern.sub(r"-[\1]-", cypher)


def check_schema(cypher, schema):
    """Devolve a lista de problemas (texto para o modelo corrigir); vazia se estiver tudo certo."""
    text = strip_strings(cypher)
    node_vars, rel_vars = variables(text)
    return (_check_directions(text, node_vars, schema) + _check_properties(text, node_vars, rel_vars, schema)
            + _check_integer_division(text))


def variables(text):
    """Label de cada variável de nó e tipo de cada variável de relação (o primeiro que aparecer)."""
    node_vars, rel_vars = {}, {}
    for var, label in NODE_VAR_LABEL.findall(text):
        node_vars.setdefault(var, label)
    for var, rel_type in REL_VAR_TYPE.findall(text):
        rel_vars.setdefault(var, rel_type)
    return node_vars, rel_vars


def _label(node_text, node_vars):
    var, label = VAR_LABEL.match(node_text).groups()
    return label or node_vars.get(var)


def _check_directions(text, node_vars, schema):
    problems = []
    nodes = list(NODE_PATTERN.finditer(text))
    for left, right in zip(nodes, nodes[1:]):
        rel = REL_BETWEEN.match(text[left.end():right.start()])
        if not rel:
            continue
        arrow_left, content, arrow_right = rel.groups()
        if bool(arrow_left) == bool(arrow_right):
            continue  # sem direção
        types = REL_TYPES.search(content or "")
        if not types or "|" in types.group(1):
            continue
        rel_type = types.group(1).strip(":")
        if rel_type in UNDIRECTED:
            continue
        src, dst = _label(left.group(1), node_vars), _label(right.group(1), node_vars)
        if arrow_left:
            src, dst = dst, src
        if src is None and dst is None:
            continue
        known = [(a, b) for a, t, b in schema.patterns if t == rel_type]
        if not known or any((src in (None, a)) and (dst in (None, b)) for a, b in known):
            continue
        allowed = ", ".join(f"(:{a})-[:{rel_type}]->(:{b})" for a, b in sorted(known))
        found = f"(:{src or ''})-[:{rel_type}]->(:{dst or ''})"
        reversed_ok = any((dst in (None, a)) and (src in (None, b)) for a, b in known)
        reason = "direção invertida" if reversed_ok else "padrão inexistente"
        problems.append(f"{reason}: a consulta usa {found}, mas no schema é {allowed}")
    return problems


def _check_properties(text, node_vars, rel_vars, schema):
    problems = []
    seen = set()
    for var, prop in PROPERTY_ACCESS.findall(text):
        if (var, prop) in seen:
            continue
        seen.add((var, prop))
        if var in node_vars:
            label = node_vars[var]
            if label not in schema.node_props or prop in schema.node_props[label]:
                continue
            owners = sorted(t for t, props in schema.rel_props.items() if prop in props)
            if owners:
                problems.append(f"`{var}.{prop}`: `{prop}` é propriedade da relação "
                                f"{'/'.join(owners)}, não do nó {label}; use a variável da relação")
            else:
                problems.append(f"`{var}.{prop}`: o nó {label} não tem a propriedade `{prop}`")
        elif var in rel_vars:
            rel_type = rel_vars[var]
            if rel_type in schema.rel_props and prop not in schema.rel_props[rel_type]:
                problems.append(f"`{var}.{prop}`: a relação {rel_type} não tem a propriedade `{prop}`")
    return problems


def _replace_integer_calls(text):
    """Troca cada size(...), count(...), length(...) e COUNT {...} (com o que tiver dentro) por INT."""
    out, pos = [], 0
    while match := INTEGER_CALL.search(text, pos):
        opening = text[match.end() - 1]
        closing = ")" if opening == "(" else "}"
        depth, end = 0, match.end() - 1
        for end in range(match.end() - 1, len(text)):
            depth += {opening: 1, closing: -1}.get(text[end], 0)
            if depth == 0:
                break
        out += [text[pos:match.start()], INT]
        pos = end + 1
    return "".join(out) + text[pos:]


def _check_integer_division(text):
    """Divisão em que os dois lados são contagens (diretas ou por alias): dá 0 ou 1, nunca 0,4."""
    text = _replace_integer_calls(text)
    integers = {INT, *INT_ALIAS.findall(text)}
    problems = []
    for left, right in DIVISION.findall(text):
        if left in integers and right in integers:
            shown = " / ".join("contagem" if x == INT else f"`{x}`" for x in (left, right))
            fix = "toFloat(...)" if left == INT else f"toFloat({left})"
            problems.append(f"{shown}: divisão entre inteiros (size/count) é divisão inteira no Cypher "
                            f"e dá 0 ou 1; use {fix} no numerador")
    return problems

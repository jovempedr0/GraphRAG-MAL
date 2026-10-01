"""Compara o resultado gerado com o da consulta de referência."""

# Diferença aceita entre números: cobre arredondamento feito pelo modelo (8,635 vs 8,64).
TOLERANCE = 0.006


def normalize(value):
    if isinstance(value, bool):
        return ("bool", value)  # True == 1.0 em Python; sem a marca, viraria número
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (list, tuple)):
        return tuple(normalize(v) for v in value)
    return str(value)


def same_value(a, b):
    if isinstance(a, float) and isinstance(b, float):
        return abs(a - b) <= TOLERANCE
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(same_value(x, y) for x, y in zip(a, b))
    return a == b


def row_contains(have, want):
    """Cada valor de `want` casa com um valor diferente de `have`."""
    free = list(have)
    for w in want:
        i = next((i for i, h in enumerate(free) if same_value(w, h)), None)
        if i is None:
            return False
        free.pop(i)
    return True


def same_result(expected_rows, got_rows):
    """Mesmo número de linhas e cada linha esperada contida numa linha gerada diferente.

    Ignora ordem das linhas, nome e ordem das colunas, e aceita colunas a mais no gerado
    (ex.: o modelo devolve também a nota). Números são comparados com tolerância.
    """
    if len(expected_rows) != len(got_rows):
        return False
    remaining = [[normalize(v) for v in row] for row in got_rows]
    for row in expected_rows:
        want = [normalize(v) for v in row]
        match = next((i for i, have in enumerate(remaining) if row_contains(have, want)), None)
        if match is None:
            return False
        remaining.pop(match)
    return True

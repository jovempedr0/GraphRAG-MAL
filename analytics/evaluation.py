"""Compara o resultado gerado com o da consulta de referência."""
from collections import Counter


def normalize(value):
    if isinstance(value, bool):
        return ("bool", value)  # True == 1.0 em Python; sem a marca, o Counter confunde os dois
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if isinstance(value, (list, tuple)):
        return tuple(normalize(v) for v in value)
    return str(value)


def same_result(expected_rows, got_rows):
    """Mesmo número de linhas e cada linha esperada contida numa linha gerada diferente.

    Ignora ordem das linhas, nome e ordem das colunas, e aceita colunas a mais no gerado
    (ex.: o modelo devolve também a nota). Números são comparados com 2 casas.
    """
    if len(expected_rows) != len(got_rows):
        return False
    remaining = [Counter(normalize(v) for v in row) for row in got_rows]
    for row in expected_rows:
        want = Counter(normalize(v) for v in row)
        match = next((i for i, have in enumerate(remaining) if not want - have), None)
        if match is None:
            return False
        remaining.pop(match)
    return True

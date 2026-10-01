"""Checagens automáticas de uma resposta em texto livre do agente (sem LLM como juiz)."""
import re
import unicodedata

DECIMAL = re.compile(r"(?<![\d.,])(\d{1,2})[.,](\d{1,2})(?![\d])")


def normalize_text(text):
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def mentions(answer, names):
    """Se algum dos nomes (título em romaji ou em inglês) aparece na resposta."""
    norm = f" {normalize_text(answer)} "
    return any(n and f" {normalize_text(n)} " in norm for n in names)


def decimals(text):
    """Números com casas decimais (notas, médias), normalizados para '8.62'."""
    return {f"{int(a)}.{b.rstrip('0') or '0'}" for a, b in DECIMAL.findall(text)}


def ungrounded_decimals(answer, sources):
    """Decimais da resposta que não aparecem em nenhum resultado de ferramenta."""
    available = set()
    for s in sources:
        available |= decimals(s)
    return sorted(decimals(answer) - available)

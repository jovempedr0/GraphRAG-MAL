"""Extração, checagem e execução segura do Cypher gerado pelo modelo."""
import re

from neo4j import unit_of_work
from neo4j.exceptions import Neo4jError

from analytics.lint import check_schema, fix_undirected, strip_strings

DEFAULT_LIMIT = 100

# Cláusulas e procedures que escrevem ou mexem no servidor. A transação de leitura já barra
# escrita, mas a checagem aqui dá uma mensagem de erro mais clara para o modelo corrigir.
WRITE_PATTERN = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|INSERT|FOREACH|LOAD\s+CSV)\b"
    r"|\b(dbms|apoc\.(create|merge|refactor|periodic|load|export|trigger|nodes\.delete))\.",
    re.IGNORECASE,
)
FENCE_PATTERN = re.compile(r"```(?:cypher)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
OPEN_FENCE_PATTERN = re.compile(r"^\s*```(?:cypher)?", re.IGNORECASE)
LIMIT_PATTERN = re.compile(r"\bLIMIT\s+\d+\s*$", re.IGNORECASE)


class CypherError(Exception):
    """Erro que volta para o modelo como pedido de correção."""


def extract_cypher(text):
    """Tira o Cypher da resposta do modelo: bloco ```cypher```, `\\n` literais e `;` final."""
    match = FENCE_PATTERN.search(text)
    cypher = match.group(1) if match else text
    # Bloco aberto e não fechado, ou ``` na mesma linha da consulta.
    cypher = OPEN_FENCE_PATTERN.sub("", cypher).replace("```", "").strip()
    if "\n" not in cypher and "\\n" in cypher:
        cypher = cypher.replace("\\n", "\n")
    return cypher.strip().rstrip(";").strip()


def check_read_only(cypher):
    # Ignora o conteúdo de strings: um título com "Set" não é escrita.
    if match := WRITE_PATTERN.search(strip_strings(cypher)):
        raise CypherError(f"consulta de escrita não permitida ({match.group(0).strip()}); use só leitura")


def ensure_limit(cypher, limit=DEFAULT_LIMIT):
    if LIMIT_PATTERN.search(cypher):
        return cypher
    return f"{cypher}\nLIMIT {limit}"


def explain(session, cypher):
    """Roda EXPLAIN: pega erro de sintaxe e label/propriedade/relação inexistente sem executar."""
    try:
        summary = session.run(f"EXPLAIN {cypher}").consume()
    except Neo4jError as e:
        raise CypherError(e.message) from e
    unknown = [s.status_description for s in summary.gql_status_objects
               if s.raw_classification == "UNRECOGNIZED"]
    if unknown:
        raise CypherError("; ".join(unknown))


def run_read(session, cypher, timeout=10.0):
    @unit_of_work(timeout=timeout)
    def work(tx):
        result = tx.run(cypher)
        return result.keys(), [list(r.values()) for r in result]

    try:
        return session.execute_read(work)
    except Neo4jError as e:
        raise CypherError(e.message) from e


def prepare_and_run(session, raw_text, schema, timeout=10.0, limit=DEFAULT_LIMIT):
    """Do texto do modelo até as linhas. Devolve (cypher executado, colunas, linhas)."""
    cypher = extract_cypher(raw_text)
    if not cypher:
        raise CypherError("resposta vazia; devolva uma consulta Cypher")
    check_read_only(cypher)
    cypher = fix_undirected(cypher)
    if problems := check_schema(cypher, schema):
        raise CypherError("; ".join(problems))
    explain(session, cypher)
    cypher = ensure_limit(cypher, limit)
    columns, rows = run_read(session, cypher, timeout)
    return cypher, columns, rows

"""As três ferramentas do agente: busca semântica, vizinhança no grafo e consulta Cypher."""
import json
import re

from agent.backends import tool_spec
from analytics.generator import generate
from ingest.embed import index_name

MAX_RESULT_CHARS = 10000
# Nós esboço têm ano, nota e episódios nulos; sem o aviso, o modelo completa de memória.
SKETCH_NOTE = ("CASE WHEN o.completo THEN null "
               "ELSE 'fora do top: o grafo não tem ano, nota nem episódios' END AS aviso")
QUERY_LANGUAGE = re.compile(r"^\s*(SELECT|MATCH|WITH|CALL|OPTIONAL|UNWIND)\b", re.IGNORECASE)
LABELS = {"anime": "Anime", "manga": "Manga"}

SPECS = [
    tool_spec(
        "busca_semantica",
        "Acha animes ou mangás pelo assunto, clima ou enredo, comparando o texto com as sinopses "
        "(ex.: 'luto e perda', 'time de vôlei do ensino médio'). Não use para achar um título "
        "específico: para isso use expandir_vizinhanca.",
        {"type": "object", "properties": {
            "texto": {"type": "string", "description": "descrição do que procurar, em qualquer idioma"},
            "tipo": {"type": "string", "enum": ["anime", "manga"]},
            "k": {"type": "integer", "minimum": 1, "maximum": 10, "description": "quantos resultados (padrão 5)"},
        }, "required": ["texto"]},
    ),
    tool_spec(
        "expandir_vizinhanca",
        "Dado um título, mostra o nó no grafo: nota, gêneros, estúdio ou autores, as recomendações "
        "dos usuários do MyAnimeList (com votos) e as obras relacionadas (sequências, spin-offs...). "
        "Com saltos=2, inclui as recomendações das recomendações. Use para 'parecido com X' e para "
        "explorar uma obra. Aceita o título em romaji ou em inglês; se não achar, devolve os parecidos.",
        {"type": "object", "properties": {
            "titulo": {"type": "string"},
            "mal_id": {"type": "integer", "description": "alternativa ao título, vinda de outra ferramenta"},
            "tipo": {"type": "string", "enum": ["anime", "manga"]},
            "saltos": {"type": "integer", "minimum": 1, "maximum": 2},
        }, "required": []},
    ),
    tool_spec(
        "consulta_cypher",
        "Responde perguntas estruturadas sobre o grafo: filtros, contagens, rankings, médias, "
        "comparações (ex.: 'animes psicológicos com nota acima de 8 e até 13 episódios', 'estúdio "
        "com maior nota média'). Recebe a pergunta em linguagem natural, completa e autocontida; "
        "gera e executa o Cypher e devolve a tabela.",
        {"type": "object", "properties": {
            "pergunta": {"type": "string"},
        }, "required": ["pergunta"]},
    ),
]


class ToolError(Exception):
    """Erro devolvido ao modelo como resultado da ferramenta."""


def validate(spec, args):
    """Checagem simples contra o schema: obrigatórios, tipos, enum e limites."""
    if args is None:
        raise ToolError("argumentos não são um JSON válido")
    props = spec["parameters"]["properties"]
    unknown = set(args) - set(props)
    if unknown:
        raise ToolError(f"argumentos desconhecidos: {', '.join(sorted(unknown))}")
    for name in spec["parameters"].get("required", []):
        if args.get(name) in (None, ""):
            raise ToolError(f"falta o argumento obrigatório '{name}'")
    if spec["name"] == "consulta_cypher" and QUERY_LANGUAGE.match(args["pergunta"]):
        raise ToolError("mande a pergunta em português, como uma pessoa perguntaria; "
                        "a ferramenta escreve o Cypher sozinha")
    for name, value in args.items():
        p = props[name]
        if p["type"] == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ToolError(f"'{name}' deve ser um inteiro")
        if p["type"] == "string" and not isinstance(value, str):
            raise ToolError(f"'{name}' deve ser texto")
        if "enum" in p and value not in p["enum"]:
            raise ToolError(f"'{name}' deve ser um de: {', '.join(p['enum'])}")
        if "minimum" in p and value < p["minimum"] or "maximum" in p and value > p["maximum"]:
            raise ToolError(f"'{name}' deve estar entre {p.get('minimum')} e {p.get('maximum')}")


def drop_nulls(value):
    if isinstance(value, dict):
        return {k: drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [drop_nulls(v) for v in value]
    return value


def to_text(result):
    text = json.dumps(drop_nulls(result), ensure_ascii=False, default=str)
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + " …(cortado)"
    return text


class Tools:
    def __init__(self, session, embedder, cypher_chat, schema):
        self.session = session
        self.embedder = embedder
        self.cypher_chat = cypher_chat
        self.schema = schema
        self.specs = {s["name"]: s for s in SPECS}

    def call(self, name, args):
        """Executa e devolve (texto do resultado, é_erro)."""
        if name not in self.specs:
            return f"ferramenta desconhecida: {name}", True
        try:
            validate(self.specs[name], args)
            return to_text(getattr(self, name)(**args)), False
        except ToolError as e:
            return str(e), True

    # --- busca_semantica -------------------------------------------------------------

    def busca_semantica(self, texto, tipo="anime", k=5):
        label = LABELS[tipo]
        vector = self.embedder.embed_query(texto)
        # Pega mais candidatos e mostra um por franquia: a busca por "vôlei" devolveria
        # cinco temporadas de Haikyuu.
        rows = self.session.run(f"""
            CALL db.index.vector.queryNodes($index, $n, $vector) YIELD node, score
            RETURN node.mal_id AS mal_id, node.titulo AS titulo, node.titulo_en AS titulo_en,
                   node.ano AS ano, node.nota AS nota, node.tipo AS formato,
                   node.{'episodios' if label == 'Anime' else 'capitulos'} AS {'episodios' if label == 'Anime' else 'capitulos'},
                   [(node)-[:HAS_GENRE]->(g) | g.nome] AS generos,
                   left(node.sinopse, 300) AS sinopse, round(score, 3) AS score
            """, index=index_name(label, len(vector)), n=k * 4, vector=vector).data()
        franchise = dict(self.session.run(f"""
            UNWIND $ids AS id
            MATCH (n:{label} {{mal_id: id}})
            OPTIONAL MATCH (n)-[:RELATED_TO*1..6]-(m:{label}) WHERE m.mal_id IN $ids
            RETURN id, collect(DISTINCT m.mal_id) AS mesmos
            """, ids=[r["mal_id"] for r in rows]).values())
        picked, seen = [], set()
        for r in rows:
            if r["mal_id"] in seen:
                continue
            seen.add(r["mal_id"])
            seen.update(franchise.get(r["mal_id"], []))
            picked.append(r)
            if len(picked) == k:
                break
        return {"resultados": picked,
                "obs": "um resultado por franquia; score só serve para ordenar (valores próximos entre si)"}

    # --- expandir_vizinhanca -------------------------------------------------------------

    def resolve(self, label, titulo=None, mal_id=None):
        if mal_id is not None:
            found = self.session.run(f"MATCH (n:{label} {{mal_id: $id}}) RETURN n.mal_id", id=mal_id).value()
            if not found:
                raise ToolError(f"{label} com mal_id {mal_id} não existe")
            return mal_id
        if not titulo:
            raise ToolError("informe 'titulo' ou 'mal_id'")
        exact = self.session.run(f"""
            MATCH (n:{label}) WHERE toLower(n.titulo) = toLower($t) OR toLower(n.titulo_en) = toLower($t)
            RETURN n.mal_id ORDER BY n.completo DESC, coalesce(n.membros, 0) DESC LIMIT 1
            """, t=titulo).value()
        if exact:
            return exact[0]
        similar = self.session.run(f"""
            MATCH (n:{label})
            WHERE toLower(n.titulo) CONTAINS toLower($t) OR toLower(coalesce(n.titulo_en, '')) CONTAINS toLower($t)
            RETURN n.titulo AS titulo, n.mal_id AS mal_id ORDER BY coalesce(n.membros, 0) DESC LIMIT 5
            """, t=titulo).data()
        if similar:
            raise ToolError(f"título '{titulo}' não encontrado exatamente; parecidos: {to_text(similar)}. "
                            "Chame de novo com o título exato ou o mal_id")
        raise ToolError(f"título '{titulo}' não encontrado; tente busca_semantica ou outra grafia")

    def expandir_vizinhanca(self, titulo=None, mal_id=None, tipo="anime", saltos=1):
        label = LABELS[tipo]
        node_id = self.resolve(label, titulo, mal_id)
        is_anime = label == "Anime"
        info = self.session.run(f"""
            MATCH (n:{label} {{mal_id: $id}})
            RETURN n.mal_id AS mal_id, n.titulo AS titulo, n.titulo_en AS titulo_en, n.completo AS completo,
                   n.nota AS nota, n.ano AS ano, n.tipo AS formato, n.status AS status,
                   {'n.episodios AS episodios, n.fonte AS fonte' if is_anime else 'n.capitulos AS capitulos'},
                   [(n)-[:HAS_GENRE]->(g) | g.nome] AS generos,
                   {'[(n)-[:PRODUCED_BY]->(s) | s.nome] AS estudios' if is_anime else '[(n)-[:WRITTEN_BY]->(p) | p.nome] AS autores'},
                   left(n.sinopse, 400) AS sinopse
            """, id=node_id).single().data()
        if not info["completo"]:
            info["obs"] = "nó esboço (fora do top): só título e conexões, sem nota nem gêneros"

        info["recomendacoes"] = self.session.run(f"""
            MATCH (n:{label} {{mal_id: $id}})-[r:RECOMMENDS]-(o)
            RETURN o.titulo AS titulo, o.mal_id AS mal_id, r.votos AS votos, o.nota AS nota,
                   {'o.episodios AS episodios' if is_anime else 'o.capitulos AS capitulos'}, o.ano AS ano,
                   {SKETCH_NOTE}
            ORDER BY r.votos DESC LIMIT 15
            """, id=node_id).data()
        # (a)-[:RELATED_TO {tipo}]->(b) = "b é `tipo` de a"; aqui o texto já vem resolvido.
        info["relacionados"] = self.session.run(f"""
            MATCH (n:{label} {{mal_id: $id}})-[r:RELATED_TO]-(o)
            RETURN o.titulo AS titulo, o.mal_id AS mal_id,
                   CASE WHEN startNode(r) = n THEN 'é ' + r.tipo + ' desta obra'
                        ELSE 'esta obra é ' + r.tipo + ' dela' END AS relacao,
                   o.ano AS ano
            ORDER BY o.ano LIMIT 15
            """, id=node_id).data()
        # Ordem para assistir/ler: da primeira à última obra da cadeia de sequências.
        chain = self.session.run(f"""
            MATCH (n:{label} {{mal_id: $id}})
            MATCH (root:{label})-[:RELATED_TO*0..20 {{tipo: 'sequel'}}]->(n)
            WHERE NOT ()-[:RELATED_TO {{tipo: 'sequel'}}]->(root)
            WITH root LIMIT 1
            MATCH p = (root)-[:RELATED_TO*0..20 {{tipo: 'sequel'}}]->(last)
            WHERE NOT (last)-[:RELATED_TO {{tipo: 'sequel'}}]->()
            WITH p ORDER BY length(p) DESC LIMIT 1
            RETURN [x IN nodes(p) | {{titulo: x.titulo, ano: x.ano, nota: x.nota,
                    {'episodios: x.episodios' if is_anime else 'capitulos: x.capitulos'}}}] AS ordem
            """, id=node_id).value()
        if chain and len(chain[0]) > 1:
            info["cadeia_de_sequencias"] = chain[0]
        if saltos == 2:
            info["segundo_grau"] = self.session.run(f"""
                MATCH (n:{label} {{mal_id: $id}})-[:RECOMMENDS]-(v)-[r2:RECOMMENDS]-(o:{label})
                WHERE o <> n AND NOT (n)-[:RECOMMENDS]-(o)
                RETURN o.titulo AS titulo, o.mal_id AS mal_id, o.nota AS nota,
                       count(DISTINCT v) AS caminhos, sum(r2.votos) AS forca, {SKETCH_NOTE}
                ORDER BY caminhos DESC, forca DESC LIMIT 10
                """, id=node_id).data()
        return info

    # --- consulta_cypher -------------------------------------------------------------

    def consulta_cypher(self, pergunta):
        ans = generate(pergunta, self.cypher_chat, self.session, self.schema)
        if not ans.ok:
            errors = [a.error for a in ans.attempts if a.error]
            raise ToolError(f"não consegui gerar uma consulta válida. Erros: {to_text(errors)}")
        return {"cypher": ans.cypher, "colunas": ans.columns, "linhas": ans.rows[:50],
                "total_linhas": len(ans.rows)}

#!/usr/bin/env bash
# Ponto de entrada único do projeto. Uso: ./run.sh <comando> [args]   (./run.sh ajuda)
set -eo pipefail  # sem -u: o bash 3.2 do macOS acusa "$@" vazio
cd "$(dirname "$0")"

ENV_FILE=config/.env
R() { uv run --env-file "$ENV_FILE" "$@"; }
step() { printf '\n===== %s %s\n' "$(date +%T)" "$*"; }
die() { echo "erro: $*" >&2; exit 1; }
env_get() { { grep -E "^$1=" "$ENV_FILE" || true; } | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//'; }
need_env() { [[ -f $ENV_FILE ]] || die "falta $ENV_FILE; rode ./run.sh setup e preencha as chaves"; }
compose() { docker compose --env-file "$ENV_FILE" "$@"; }

ajuda() {
  cat <<'EOF'
Uso: ./run.sh <comando> [args]

Preparação
  setup                 instala as dependências (uv sync) e cria config/.env a partir do exemplo
  db                    sobe o Neo4j (Docker), espera ficar pronto e cria constraints e índices
  check                 confere Neo4j, oMLX e os modelos configurados

Dados
  ingest [N]            top N animes e mangás (padrão 500) → carga → embeddings → ADAPTED_FROM
  crawl                 coleta a fronteira, carrega e refaz embeddings e ADAPTED_FROM (com busca reversa)
  dados [N]             ingest + crawl

Uso
  ui [porta]            interface web (padrão 8765)
  compartilhar [porta]  interface web + túnel ngrok com senha (UI_BASIC_AUTH no .env, ou gera uma)
  agente [pergunta]     agente no terminal; sem pergunta, modo conversa
  analytics <pergunta>  pergunta → Cypher → tabela

Avaliação e testes
  eval [alvo]           gerador | agente | abc | tudo (padrão: gerador + agente)
  test                  pytest

Tudo
  tudo [N]              db + dados + eval
EOF
}

setup() {
  command -v uv >/dev/null || die "instale o uv: https://docs.astral.sh/uv/"
  uv sync
  if [[ ! -f $ENV_FILE ]]; then
    cp config/.env.example "$ENV_FILE"
    echo "criado $ENV_FILE: preencha MAL_CLIENT_ID, NEO4J_PASSWORD e OMLX_API_KEY"
  fi
}

db() {
  need_env
  step "subindo o Neo4j"
  compose up -d --wait
  step "constraints e índices"
  compose exec -T neo4j sh -c 'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" -f /schema/constraints.cypher'
  echo "Neo4j pronto: http://localhost:7474"
}

check() {
  need_env
  local ok=0 base key models m
  if [[ "$(compose ps --format '{{.Health}}' neo4j 2>/dev/null)" == healthy ]]; then
    echo "✅ Neo4j"
  else
    echo "❌ Neo4j fora do ar (./run.sh db)"; ok=1
  fi
  base=$(env_get OMLX_BASE_URL); key=$(env_get OMLX_API_KEY)
  if models=$(curl -sf -m 5 -H "Authorization: Bearer $key" "${base:-http://localhost:8000/v1}/models"); then
    echo "✅ oMLX em ${base:-http://localhost:8000/v1}"
    for m in "$(env_get CYPHER_MODEL)" "$(env_get EMBEDDING_MODEL)"; do
      if grep -q "\"$m\"" <<<"$models"; then echo "✅ modelo $m"; else echo "❌ modelo $m não está no oMLX"; ok=1; fi
    done
  else
    echo "❌ oMLX não responde em ${base:-http://localhost:8000/v1} (confira o servidor e OMLX_API_KEY)"; ok=1
  fi
  return $ok
}

ingest() {
  need_env
  local n=${1:-500}
  step "1/5 top $n animes";   R python -m ingest.fetch anime --limit "$n"
  step "2/5 top $n mangás";   R python -m ingest.fetch manga --limit "$n"
  step "3/5 carga";           R python -m ingest.load
  step "4/5 embeddings";      R python -m ingest.embed
  step "5/5 ADAPTED_FROM";    R python -m ingest.adapt
}

crawl() {
  need_env
  step "1/8 crawl de animes";            R python -m ingest.crawl anime --min-recomendacoes 2
  step "2/8 crawl de mangás";            R python -m ingest.crawl manga
  step "3/8 carga";                      R python -m ingest.load
  step "4/8 embeddings";                 R python -m ingest.embed
  step "5/8 ADAPTED_FROM + busca reversa"; R python -m ingest.adapt --buscar
  step "6/8 carga dos animes achados";   R python -m ingest.load
  step "7/8 embeddings";                 R python -m ingest.embed
  step "8/8 ADAPTED_FROM";               R python -m ingest.adapt
}

eval_() {
  need_env
  local model; model=$(env_get CYPHER_MODEL)
  [[ -n $model ]] || die "defina CYPHER_MODEL em $ENV_FILE"
  case ${1:-padrao} in
    gerador)
      step "gerador: perguntas antigas"; R python -m eval.run "$model"
      step "gerador: perguntas novas";   R python -m eval.run "$model" --perguntas eval/questions_novas.json ;;
    agente)
      step "agente";                     R python -m eval.agent_run ;;
    abc)
      step "A/B/C: A (só LLM)";          R python -m eval.agent_run --config A --max-tokens 16384
      step "A/B/C: B (RAG vetorial)";    R python -m eval.agent_run --config B
      step "A/B/C: C (GraphRAG)";        R python -m eval.agent_run --config C ;;
    padrao) eval_ gerador; eval_ agente ;;
    tudo)   eval_ gerador; eval_ abc ;;
    *) die "alvo de eval desconhecido: $1 (gerador | agente | abc | tudo)" ;;
  esac
}

compartilhar() {
  need_env
  command -v ngrok >/dev/null || die "instale o ngrok (brew install ngrok) e rode: ngrok config add-authtoken <token>"
  local port=${1:-8765} auth ui_pid
  # A interface não tem login: sem senha no túnel, qualquer um com o link usa o agente e o banco
  auth=$(env_get UI_BASIC_AUTH)
  if [[ -z $auth ]]; then
    auth="graphrag:$(openssl rand -hex 8)"  # tr </dev/urandom | head morreria de SIGPIPE com pipefail
    echo "UI_BASIC_AUTH não definido em $ENV_FILE; senha gerada para esta sessão"
  fi
  local pass=${auth#*:}
  [[ $pass != "$auth" && ${#pass} -ge 8 ]] || die "UI_BASIC_AUTH deve ser usuario:senha, com senha de 8+ caracteres"
  step "interface na porta $port"
  R uvicorn ui.server:app --port "$port" --log-level warning &
  ui_pid=$!
  # uv run nem sempre repassa o sinal ao uvicorn: encerra pelo comando. INT/TERM precisam sair do script.
  trap "pkill -f 'uvicorn ui.server:app --port $port' 2>/dev/null || true" EXIT
  trap 'exit 130' INT TERM
  for _ in $(seq 30); do curl -s -m 2 -o /dev/null "http://localhost:$port/" && break; sleep 1; done
  kill -0 $ui_pid 2>/dev/null || die "a interface não subiu"
  step "túnel ngrok (Ctrl+C encerra os dois)"
  echo "login: ${auth%%:*}   senha: ${auth#*:}"
  echo "o endereço público aparece em Forwarding, logo abaixo"
  sleep 2
  ngrok http "$port" --basic-auth "$auth"
}

cmd=${1:-ajuda}; shift || true
case $cmd in
  setup)     setup ;;
  db)        db ;;
  check)     check ;;
  ingest)    ingest "$@" ;;
  crawl)     crawl ;;
  dados)     ingest "$@"; crawl ;;
  ui)        need_env; R uvicorn ui.server:app --port "${1:-8765}" ;;
  compartilhar) compartilhar "$@" ;;
  agente)    need_env; R python -m agent "$@" ;;
  analytics) need_env; [[ $# -gt 0 ]] || die "uso: ./run.sh analytics \"pergunta\""; R python -m analytics "$@" ;;
  eval)      eval_ "$@" ;;
  test)      uv run pytest -q "$@" ;;
  tudo)      db; ingest "$@"; crawl; eval_ ;;
  ajuda|-h|--help) ajuda ;;
  *) ajuda; die "comando desconhecido: $cmd" ;;
esac

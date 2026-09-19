#!/usr/bin/env bash
# Checks the tools, the repo setup, the secrets a running engine needs, and the compose services.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"
ok=0
need() {
  if command -v "$2" >/dev/null 2>&1; then
    printf '  ok      %-8s %s\n' "$1" "$($2 --version 2>/dev/null | head -1)"
  else
    printf '  MISSING %-8s install: %s\n' "$1" "$3"; ok=1
  fi
}
echo "tools:"
need just   just   "https://just.systems"
need uv     uv     "https://docs.astral.sh/uv"
need git    git    "package manager"
need docker docker "https://docs.docker.com/engine/install"
echo "repo:"
[ -f .env ] && echo "  ok      .env" || { echo "  MISSING .env        run: just env"; ok=1; }
[ "$(git config core.hooksPath)" = ".githooks" ] && echo "  ok      git hooks" || echo "  MISSING git hooks   run: just hooks"
if uv sync --locked --all-packages --inexact --check >/dev/null 2>&1; then
  echo "  ok      dependencies"
else
  echo "  MISSING dependencies  run: just setup"; ok=1
fi
echo "secrets:"
secret() {
  if [ -f .env ] && grep -qE "^$1=.+" .env; then
    printf '  ok      %s\n' "$1"
  else
    printf '  unset   %s  %s\n' "$1" "$2"
  fi
}
secret ZIPY_PLATFORMS__DISCORD__TOKEN "discord cannot connect"
secret ZIPY_MODELS__CHAT__API_KEY "unset uses the local llama-server"
secret ZIPY_DATA__FERNET_KEY "run: just fernet-key"
secret ZIPY_PROVIDERS__GOOGLE__CLIENT_ID "google tools cannot connect"
secret ZIPY_PROVIDERS__NOTION__CLIENT_ID "notion tools cannot connect"
echo "services:"
probe() {
  if curl -fsS -m 2 "$2" >/dev/null 2>&1; then
    printf '  ok      %-12s %s\n' "$1" "$2"
  else
    printf '  down    %-12s %s  %s\n' "$1" "$2" "$3"
  fi
}
port() {
  if (exec 3<>"/dev/tcp/127.0.0.1/$2") 2>/dev/null; then
    printf '  ok      %-12s 127.0.0.1:%s\n' "$1" "$2"
  else
    printf '  down    %-12s 127.0.0.1:%s  %s\n' "$1" "$2" "$3"
  fi
}
port  "postgres"    5432 "run: just up"
port  "redis"       6379 "run: just up"
probe "chat model"  "http://127.0.0.1:8000/health" "run: just model"
probe "embed model" "http://127.0.0.1:8001/health" "run: just model"
probe "zipy"        "http://127.0.0.1:8080/health" "run: just serve"
probe "metrics"     "http://127.0.0.1:8080/metrics" "run: just serve"
probe "langfuse"    "http://127.0.0.1:3000/api/public/health" "run: just up langfuse"
probe "prometheus"  "http://127.0.0.1:9090/-/ready" "run: just up prometheus"
probe "grafana"     "http://127.0.0.1:3002/api/health" "run: just up grafana"
probe "uptime-kuma" "http://127.0.0.1:3001/" "run: just up uptime-kuma"
image=$(grep -m1 '^image = ' zipy.toml | cut -d'"' -f2)
if ! docker version >/dev/null 2>&1; then
  printf '  down    %-12s no runtime; the sandbox tool and attached files are off\n' "sandbox"
elif docker image inspect "$image" >/dev/null 2>&1; then
  printf '  ok      %-12s %s\n' "sandbox" "$image"
else
  printf '  down    %-12s %s is not built  run: just sandbox-image\n' "sandbox" "$image"
fi
echo "local state:"
for dir in .zipy/traces .zipy/logs; do
  n=$(find "$dir" -type f 2>/dev/null | wc -l)
  printf '  %-7s %-14s %s files\n' "$([ -d "$dir" ] && echo ok || echo empty)" "$dir" "$n"
done
exit $ok

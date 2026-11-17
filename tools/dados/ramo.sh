#!/bin/sh
# O ramo órfão `dados` (commit único, sem histórico): o que os workflows do espelho produzem, nos MESMOS caminhos do
# repositório do app (app/dados/…, tools/…/dados/…, android-extra/jniLibs/…), para o `tools/publico.py puxar` de lá
# copiar por cima. Só dados públicos e bibliotecas de código aberto.
#
#   sh tools/dados/ramo.sh abrir             põe o ramo por cima de espelho/ (o estado de antes; os scripts são incrementais)
#   sh tools/dados/ramo.sh guardar "motivo"  grava de volta só os CAMINHOS abaixo (precisa de TOKEN e GITHUB_REPOSITORY)
#
# Os workflows que usam este ramo têm o mesmo grupo de concorrência (`dados`): um de cada vez, para um não apagar o
# que o outro acabou de gravar.
set -e
RAMO=dados
CAMINHOS="app/dados/sia tools/odontoscan/dados/sia-estado.json tools/odontoscan/dados/sia-log.txt app/dados/xadrez/problemas.json tools/xadrez/problemas-log.txt android-extra/jniLibs"
case "$1" in
  abrir)
    if git fetch -q --depth=1 origin "$RAMO"; then git archive FETCH_HEAD | tar -x -C espelho; echo "ramo $RAMO aberto em espelho/"
    else echo "o ramo $RAMO ainda não existe"; fi
    ;;
  guardar)
    rm -rf /tmp/ramo-dados && mkdir -p /tmp/ramo-dados
    for c in $CAMINHOS; do
      if [ -e "espelho/$c" ]; then mkdir -p "/tmp/ramo-dados/$(dirname "$c")" && cp -r "espelho/$c" "/tmp/ramo-dados/$c"; fi
    done
    cp tools/dados/LEIA-ME-ramo.md /tmp/ramo-dados/LEIA-ME.md
    cd /tmp/ramo-dados
    [ -n "$(find . -type f ! -name LEIA-ME.md | head -1)" ] || { echo "nada a guardar"; exit 0; }
    git init -q
    git checkout -q -b "$RAMO"
    git config user.name "Órbita (dados públicos)"
    git config user.email "actions@users.noreply.github.com"
    git add -A
    git commit -q -m "Dados: ${2:-rodada} ($(date -u +%Y-%m-%dT%H:%MZ))"
    git push -q -f "https://x-access-token:${TOKEN}@github.com/${GITHUB_REPOSITORY}.git" "$RAMO"
    echo "guardado no ramo $RAMO: $(git ls-files | wc -l) arquivos"
    ;;
  *) echo "uso: ramo.sh abrir | guardar \"motivo\""; exit 2 ;;
esac

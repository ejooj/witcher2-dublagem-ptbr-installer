#!/bin/sh
# Dublagem PT-BR de The Witcher 2 - desinstalar no Linux / Steam Deck.
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then echo "Precisa do Python 3."; read -r _; exit 1; fi
python3 linux/dublagem_linux.py desinstalar "$@"; s=$?
printf "\nAperte Enter para fechar. "; read -r _
exit $s

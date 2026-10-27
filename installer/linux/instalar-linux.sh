#!/bin/sh
# Dublagem PT-BR de The Witcher 2 - instalar no Linux / Steam Deck (modo Desktop).
# Clique com o botão direito > "Executar" (ou abra um terminal nesta pasta e rode: sh instalar-linux.sh).
cd "$(dirname "$0")" || exit 1
if ! command -v python3 >/dev/null 2>&1; then echo "Precisa do Python 3 (o SteamOS já vem com ele)."; read -r _; exit 1; fi
python3 linux/dublagem_linux.py instalar "$@"; s=$?
printf "\nAperte Enter para fechar. "; read -r _
exit $s

#!/bin/bash
# A Luanti window joined to the demo server, for the side-by-side demo.
#
#   bridges/luanti/run/play.sh --name NAME [--port 19529]
#
# The player's password for this local server comes from the macOS keychain (service
# exulanica-gate-player, account NAME; store it once with
#   security add-generic-password -s exulanica-gate-player -a NAME -w
# ) through a file only this user can read, removed as soon as the window has started.
set -euo pipefail

name="" port=19529
while [[ $# -gt 0 ]]; do
	case $1 in
		--name) name=$2; shift 2 ;;
		--port) port=$2; shift 2 ;;
		*) echo "play: unknown option $1" >&2; exit 2 ;;
	esac
done
[[ $name =~ ^[A-Za-z0-9_-]{1,20}$ ]] || { echo "play: --name is a Luanti player name" >&2; exit 2; }

checkout=$(cd "$(dirname "$0")/../../.." && pwd)
install=$checkout/.exulanica/luanti
binary=$install/app/luanti.app/Contents/MacOS/luanti
[[ -x $binary ]] || { echo "play: run bridges/luanti/run/install.sh first" >&2; exit 1; }

mkdir -p "$install/run"
umask 077
secret=$(mktemp "$install/run/player.XXXXXX")
trap 'rm -f "$secret"' EXIT
security find-generic-password -s exulanica-gate-player -a "$name" -w > "$secret" 2>/dev/null \
	|| { echo "play: no password in the keychain for $name" >&2; exit 1; }

LUANTI_USER_PATH=$install/user LUANTI_GAME_PATH=$install/games \
	"$binary" --go --address 127.0.0.1 --port "$port" --name "$name" --password-file "$secret" \
	--logfile "$install/run/client.log" &
sleep 5
rm -f "$secret"
wait

#!/bin/bash
# The demo server on this Mac: Luanti 5.17.0 from the unpacked install (run/install.sh), bound to
# 127.0.0.1 on one UDP port, playing Minetest Game in a flat, always-noon demo world with a gate
# five nodes in front of the spawn. Runs in the foreground; stop it with Ctrl-C.
#
#   bridges/luanti/run/serve.sh --door URL [--world NAME] [--port 19529] [--allow NAMES]
#
# The world's channel credential comes from the macOS keychain (service exulanica-gate, account
# the world's name) into the server process's environment and nowhere else. Store it once with
#   security add-generic-password -s exulanica-gate -a <world name> -w
# which asks for the value, so it is never typed on a command line or written to a file.
set -euo pipefail

door="" world="exulanica-demo" port=19529 allow=""
while [[ $# -gt 0 ]]; do
	case $1 in
		--door) door=$2; shift 2 ;;
		--world) world=$2; shift 2 ;;
		--port) port=$2; shift 2 ;;
		--allow) allow=$2; shift 2 ;;
		*) echo "serve: unknown option $1" >&2; exit 2 ;;
	esac
done
[[ -n $door ]] || { echo "serve: --door names the Exulanica door's address" >&2; exit 2; }
[[ $world =~ ^[a-z0-9-]+$ ]] || { echo "serve: a world name is lowercase letters, digits and hyphens" >&2; exit 2; }

checkout=$(cd "$(dirname "$0")/../../.." && pwd)
install=$checkout/.exulanica/luanti
binary=$install/app/luanti.app/Contents/MacOS/luanti
[[ -x $binary ]] || { echo "serve: run bridges/luanti/run/install.sh first" >&2; exit 1; }

folder=$install/user/worlds/$world
if [[ ! -f $folder/world.mt ]]; then
	mkdir -p "$folder"
	printf '%s\n' "gameid = minetest_game" "backend = sqlite3" "player_backend = sqlite3" \
		"auth_backend = sqlite3" "mod_storage_backend = sqlite3" "load_mod_exulanica_gate = true" \
		> "$folder/world.mt"
fi
mkdir -p "$install/run"
config=$install/run/$world.conf
{
	echo "bind_address = 127.0.0.1"
	echo "ipv6_server = false"
	echo "port = $port"
	echo "server_announce = false"
	echo "secure.http_mods = exulanica_gate"
	echo "disallow_empty_password = true"
	echo "max_users = 4"
	echo "enable_damage = false"
	echo "mg_name = flat"
	echo "fixed_map_seed = 2026"
	echo "static_spawnpoint = (0, 10, 0)"
	echo "time_speed = 0"
	echo "world_start_time = 12000"
	echo "exulanica_gate.door_url = $door"
	echo "exulanica_gate.gate_at_spawn = true"
	echo "exulanica_gate.record_exchanges = true"
	echo "exulanica_gate.allowed_players = $allow"
} > "$config"

credential=$(security find-generic-password -s exulanica-gate -a "$world" -w 2>/dev/null || true)
[[ -n $credential ]] || echo "serve: no channel credential in the keychain for $world; the gate opens only by invites" >&2

EXULANICA_GATE_CHANNEL_CREDENTIAL=$credential \
LUANTI_USER_PATH=$install/user \
LUANTI_GAME_PATH=$install/games \
LUANTI_MOD_PATH=$checkout/bridges/luanti/mod \
	exec "$binary" --server --world "$folder" --gameid minetest_game --port "$port" \
	--config "$config" --logfile "$install/run/$world.log"

#!/bin/bash
# Unpack the two allocated archives into this checkout's ignored .exulanica/luanti/, after checking
# each one's SHA-256. Never downloads anything: the archives are the ones the operator's allocation
# names, kept outside the repository, and the folder holding them is the one argument.
#
#   bridges/luanti/run/install.sh ARCHIVES_FOLDER
#
# Results: .exulanica/luanti/app/luanti.app (the engine, LGPL-2.1-or-later; its media CC BY-SA 3.0),
# .exulanica/luanti/games/minetest_game (code LGPL-2.1-or-later, media CC BY-SA 3.0) and an empty
# .exulanica/luanti/user, which the run scripts give the engine as LUANTI_USER_PATH so nothing is
# written to the operator's home folder.
set -euo pipefail

archives=${1:?the folder holding the two allocated archives}
checkout=$(cd "$(dirname "$0")/../../.." && pwd)
target=$checkout/.exulanica/luanti

engine=luanti_5.17.0_macos12.3_arm64.zip
engine_sha256=0ba118b537d3cc6fd07cd2268fef25e515fc6d87c27ad69b476144a8e28dba3c
game=minetest_game-release-38214.zip
game_sha256=5b364f6b0cf31ec336319492e14106d932eb86b65a91ded99f4b25f4876519dc

check() {
	local found
	found=$(shasum -a 256 "$archives/$1" | cut -d' ' -f1)
	if [[ $found != "$2" ]]; then
		echo "install: $1 has sha256 $found, not the allocated $2" >&2
		exit 1
	fi
}
check "$engine" "$engine_sha256"
check "$game" "$game_sha256"

git -C "$checkout" check-ignore -q "$target" || { echo "install: $target is not ignored by git" >&2; exit 1; }
mkdir -p "$target"
scratch=$(mktemp -d "$target/unpack.XXXXXX")
unzip -q "$archives/$engine" -d "$scratch/app"
rm -rf "$scratch/app/__MACOSX"
unzip -q "$archives/$game" -d "$scratch/games"
rm -rf "$target/app" "$target/games"
mv "$scratch/app" "$target/app"
mv "$scratch/games" "$target/games"
rmdir "$scratch"
mkdir -p "$target/user"
echo "installed: $target/app/luanti.app and $target/games/minetest_game"

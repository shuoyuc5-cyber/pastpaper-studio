#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
revision="$(git rev-parse --verify "${1:-HEAD}^{commit}")"
target="${2:?Specify a fresh output directory}"
mkdir -- "$target"
umask 077
git archive --format=tar.gz --prefix="pastpaper-${revision:0:12}/" "$revision" > "$target/source.tar.gz"
(
  cd "$target"
  shasum -a 256 source.tar.gz > SHA256SUMS
  printf '%s\n' "$revision" > REVISION
  shasum -a 256 -c SHA256SUMS
)

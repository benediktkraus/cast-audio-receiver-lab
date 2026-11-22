#!/bin/sh
# Builds the DSM overlay image from this checkout: vibecast at the Containerfile's pinned commit
# + patches/vibecast-0.8.0.dev2-current.patch + patches/vibecast-soundcloud.patch, compiled in the
# Containerfile's rust image; then layers it and the DLNA bridge over the published base image.
# usage: deploy/dsm/build.sh [tag]   (needs docker; writes deploy/dsm/out/image.tar.gz)
set -eu
cd "$(dirname "$0")/../.."
TAG=${1:-cast-audio-receiver:0.8.0-dev2-sc}
REV=$(git rev-parse --short HEAD)
VC_REPO=$(sed -n 's/^ARG VIBECAST_REPOSITORY=//p' Containerfile)
VC_COMMIT=$(sed -n 's/^ARG VIBECAST_COMMIT=//p' Containerfile)
RUST=$(sed -n 's/^FROM \(rust:[^ ]*\) AS vibecast-builder/\1/p' Containerfile)
OUT=deploy/dsm/out; rm -rf "$OUT"; mkdir -p "$OUT"
docker run --rm -v "$PWD/patches:/patches:ro" -v "$PWD/$OUT:/out" -v cast-receiver-cargo:/usr/local/cargo/registry "$RUST" sh -ec "
  git clone -q --filter=blob:none $VC_REPO /src && cd /src && git checkout -q --detach $VC_COMMIT
  git apply /patches/vibecast-0.8.0.dev2-current.patch && git apply /patches/vibecast-soundcloud.patch
  cargo build -q --locked --release -p vibecast-cli && cp target/release/vibecast /out/vibecast"
cp src/cast_audio_lab/dlna.py src/cast_audio_lab/dlna_media.py src/cast_audio_lab/cast_output.py src/cast_audio_lab/group_output.py src/cast_audio_lab/routes.py src/cast_audio_lab/output_registry.py src/cast_audio_lab/management.py src/cast_audio_lab/vibecast_player.py deploy/dsm/Dockerfile "$OUT/"
docker build -q --build-arg REVISION="$REV" -t "$TAG-$REV" "$OUT" >/dev/null
docker save "$TAG-$REV" | gzip -1 > "$OUT/image.tar.gz"
echo "$TAG-$REV $(sha256sum "$OUT/vibecast" | cut -c1-16) $OUT/image.tar.gz"

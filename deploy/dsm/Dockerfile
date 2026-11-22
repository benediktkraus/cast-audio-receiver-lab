# Overlay on the published 0.8.0-dev2 image: the locally patched vibecast binary and DLNA bridge.
# Functionally identical to a full Containerfile build of this branch, ~20 MB to ship instead of ~1 GB.
FROM ghcr.io/allcrafter1/cast-audio-receiver@sha256:c3ee8a484939512fe57a9dcb763804c5a01542243489bdc8ab396934bb93b2b8
COPY --chmod=0755 vibecast /usr/local/bin/vibecast
COPY --chmod=0644 dlna.py dlna_media.py /usr/local/lib/python3.15/site-packages/cast_audio_lab/
ARG REVISION=unknown
LABEL org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.description="cast-audio-receiver 0.8.0-dev2 + SoundCloud provider + DLNA streaming (branch soundcloud)"

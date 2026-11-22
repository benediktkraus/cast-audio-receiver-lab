# Overlay on the published 0.8.0-dev2 image: the locally patched vibecast binary and DLNA bridge.
# Functionally identical to a full Containerfile build of this branch, ~20 MB to ship instead of ~1 GB.
FROM ghcr.io/allcrafter1/cast-audio-receiver@sha256:c3ee8a484939512fe57a9dcb763804c5a01542243489bdc8ab396934bb93b2b8
COPY --chmod=0755 vibecast /usr/local/bin/vibecast
COPY --chmod=0644 *.py /usr/local/lib/python3.15/site-packages/cast_audio_lab/
# DSM's legacy builder ignores COPY --chmod: set modes explicitly.
RUN chmod 0755 /usr/local/bin/vibecast && chmod 0644 /usr/local/lib/python3.15/site-packages/cast_audio_lab/*.py \
 && pip install --no-cache-dir --no-deps pychromecast==14.0.9 casttube==0.2.1 protobuf==6.32.0
ARG REVISION=unknown
LABEL org.opencontainers.image.revision=$REVISION \
      org.opencontainers.image.description="cast-audio-receiver 0.8.0-dev2 + SoundCloud provider + DLNA streaming (branch soundcloud)"

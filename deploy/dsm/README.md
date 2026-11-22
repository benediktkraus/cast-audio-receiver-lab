# DSM deployment (Yamaha Cast)

Branch `soundcloud`: SoundCloud provider + DLNA streaming for Yamaha MusicCast. Background and measurements:
smart-home project `WORKLOG.md` / `ISSUES.md` (22.11.2026).

1. Build on a docker host (gaming-wsl): `deploy/dsm/build.sh` -> `deploy/dsm/out/image.tar.gz`, prints the tag.
2. Ship to the NAS and load: `scp -O image.tar.gz admin@dsm:/volume1/docker/cast-audio-receiver/` then
   `sudo docker load -i ... && rm ...`.
3. Run: copy `docker-compose.yml` to `/volume1/docker/cast-audio-receiver/`, then
   `sudo REVISION=<commit> docker-compose up -d` (DSM 7.1 ships docker-compose v1).
4. Check: `curl http://127.0.0.1:8788/health` -> `ready: true`, `running_routes: 1`; route "Yamaha Cast" lives in
   `/volume1/docker/cast-audio-receiver/data` and survives image changes.

Rollback: set `REVISION` to the previous commit (images stay loaded), or run the upstream image
`ghcr.io/allcrafter1/cast-audio-receiver@sha256:c3ee8a48...` with the same volume.

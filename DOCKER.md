# Running Mine Field 3D in Docker (e.g. on Proxmox)

The server runs in one container built straight from this repository. Player data (profiles, leaderboards, replays) and bot models live in `docker-data/` next to the code, outside the container. Updating the game rebuilds the container and keeps all of it.

## 1. Make a home for it in Proxmox

Docker runs well in a Debian LXC container. A VM works too: skip to step 2 inside it.

1. In the Proxmox web UI, download a Debian 12 container template: **local storage → CT Templates → Templates → debian-12-standard**.
2. **Create CT**:
   - **Unprivileged container:** leave it ticked.
   - **Disk:** 16 GB.
   - **CPU:** 2 cores.
   - **Memory:** 2048 MB. Use 4096 MB and more cores if you'll train bots there.
   - **Network:** DHCP, or a fixed IP so the address doesn't change.
3. Before starting it, open the container's **Options → Features** and tick **keyctl** and **nesting**. Docker needs both.
4. Start the container and open its **Console**. Log in as root.

## 2. Install Docker and the game

```sh
apt update && apt install -y git curl
curl -fsSL https://get.docker.com | sh

git clone https://github.com/FlyingChad/mine-field-3d.git
cd mine-field-3d
chmod +x update.sh
./update.sh
```

The first build takes a few minutes, because it downloads PyTorch for the bots. When it's done, open `http://<container-ip>:8080` from any device on your network. `ip -4 addr` in the console shows the container's IP.

## 3. Updating

After new code is pushed to GitHub, run this in the container's console:

```sh
cd ~/mine-field-3d && ./update.sh
```

It pulls the new code, rebuilds and restarts. Updates that don't change the dependencies take seconds, since the Python packages are cached in the image. Profiles, leaderboards, replays and models are kept. Games in progress end when the server restarts, so update between games.

**Automatic updates (optional):** to check GitHub every 10 minutes and update only when something changed, run `crontab -e` and add:

```
*/10 * * * * cd /root/mine-field-3d && git fetch -q && [ "$(git rev-parse HEAD)" != "$(git rev-parse @{u})" ] && ./update.sh >> /root/minefield-update.log 2>&1
```

## Your own bot models

Only the starter models (`demo` and `allmodes`) come with the repository. To copy models you've trained on your PC, run this on the PC from the project folder (Windows 10+ has `scp` built in):

```
scp models\*.pt root@<container-ip>:/root/mine-field-3d/docker-data/models/
```

They show up in the lab's model lists straight away, with no restart.

## Settings

All of these are in `docker-compose.yml`. Run `./update.sh` (or `docker compose up -d`) after changing them.

- **Port:** change `"8080:8080"` to, say, `"80:8080"` to serve on port 80.
- **The AI lab (`/lab`) has no login.** Anyone who can open it can start training runs (heavy on the CPU), add bots or delete models. That's fine on your home network. If the server is reachable from the internet, set `MF3D_LAB: "0"` to turn the lab off. Without the lab there's no way to add bots to games.
- **Smaller image:** `WITH_AI: "0"` leaves out PyTorch (about 700 MB). Then there are no bots and no lab.
- **Training:** the container has PyTorch for the CPU only. Bots play fine on a CPU, but training is much slower than on a gaming GPU, so it's best to train on your PC and copy the models over.

## Install as an app on phones

Fullscreen works over plain `http://`, but phones only offer **Install as an app** over `https://`. To get that, put the game behind a reverse proxy with a certificate, for example:
- Nginx Proxy Manager or Caddy, with a domain name pointing at your network;
- a Cloudflare Tunnel, which needs no open ports.

The proxy must pass WebSockets through (`/ws` and `/lab/ws`).

## Useful commands

```sh
docker compose logs -f      # the server's output (Ctrl+C to stop watching)
docker compose restart      # restart without rebuilding
docker compose down         # stop it (data in docker-data/ is kept)
```

# BYD Web Console

A standalone FastAPI + Jinja web app built around [`pyBYD`](https://github.com/jkaberg/pyBYD.git).

It is designed to:

- run in Docker and optionally be controlled by `systemd`
- show live BYD vehicle telemetry in the browser
- expose remote command buttons and options
- be reverse-proxied by Caddy or nginx if you want HTTPS

## Features

- live vehicle information on page load
- lock and unlock
- start and stop climate with temperature and duration options
- find car and flash lights
- close windows
- battery heat on and off
- steering wheel heat on and off
- driver and passenger seat heat level controls
- GPS map panel when location data is available

## Configuration

Copy the example file and fill in your BYD account details:

```bash
cp .env.example .env
```

Required values:

```env
BYD_USERNAME=your-byd-login
BYD_PASSWORD=your-byd-password
```

Required for remote commands:

```env
BYD_CONTROL_PIN=123456
```

Optional:

```env
BYD_VIN=your-vin-if-you-have-more-than-one-vehicle
BYD_TIME_ZONE=Australia/Melbourne
BYD_BASE_URL=https://dilinksuperappserver-au.byd.auto
HOST=0.0.0.0
PORT=8010
```

## Run locally

```bash
cd byd-web-console
chmod +x run.sh
./run.sh
```

Open [http://localhost:8010](http://localhost:8010).

## Run in Docker

Copy the env file first:

```bash
cp .env.example .env
nano .env
```

Build and run:

```bash
docker compose up -d --build
```

Check logs:

```bash
docker compose logs -f
```

Stop:

```bash
docker compose down
```

The app will be available on `http://<host>:8010` by default.

## Run Docker with systemd

```bash
sudo mkdir -p /opt/byd-web-console
sudo rsync -av ./ /opt/byd-web-console/
cd /opt/byd-web-console
cp .env.example .env
nano .env
sudo cp deploy/byd-web-console-container.service /etc/systemd/system/byd-web-console.service
```

This unit uses Docker Compose, so the host no longer needs Python 3.11 installed locally.

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable byd-web-console
sudo systemctl start byd-web-console
sudo systemctl status byd-web-console
```

Follow logs with:

```bash
journalctl -u byd-web-console -f
```

## Reverse proxy

Example Caddy config:

```caddyfile
byd.example.com {
  encode gzip zstd
  reverse_proxy 127.0.0.1:8010
}
```

## Notes

- The app fetches fresh telemetry on each page load instead of relying on a background database.
- If `BYD_CONTROL_PIN` is not set, telemetry still works but remote action buttons are disabled.
- The Docker image uses Python 3.11 inside the container, which avoids Debian 11 host Python limitations.
- The provided container `systemd` unit assumes deployment to `/opt/byd-web-console`.

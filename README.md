<img src="./colorfulgraphene_widescreen.jpg" alt="Colorful graphene e-ink preview" width="900">

## E-ink image server

<img src="./eink_rpi.jpg" alt="Raspberry Pi with attached e-ink display showing an image" width="300">

### Install on a Raspberry Pi

Install basic system tools:

```bash
sudo apt update
sudo apt install -y curl git
```

Enable SPI for the Waveshare display:

```bash
sudo raspi-config
```

In `raspi-config`, open `Interface Options`, enable `SPI`, then reboot:

```bash
sudo reboot
```

Install uv:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new shell, then check uv is available:

```bash
uv --version
```

Clone or copy this repository onto the Pi, then install the Python environment
from the lockfile:

```bash
cd eink_server
uv sync
```

This project is pinned to Python `3.11` in `.python-version` and requires
Python `>=3.11` in `pyproject.toml`. If the Pi does not already have Python
3.11, uv will try to provide a matching interpreter.

If GPIO or SPI access fails, make sure your user can access the Pi hardware
interfaces, then log out and back in:

```bash
sudo usermod -aG gpio,spi "$USER"
```

The display code uses `gpiozero` with the `lgpio` pin factory. If you see
warnings about falling back from `lgpio` or an error under `/sys/class/gpio`,
refresh the uv environment so the Python `lgpio` package is installed:

```bash
uv sync
```

Run the webserver with uv:

```bash
uv run eink-server --host 0.0.0.0 --port 8000
```

On a development machine without the Waveshare display attached, use dry-run mode:

```bash
EINK_DRY_RUN=1 uv run eink-server --host 127.0.0.1 --port 8000
```

Open `http://<pi-address>:8000/`. The upload tab stores the original image in
`images_raw/`, crops it to the Waveshare `400x600`/`600x400` aspect ratio,
Floyd-Steinberg dithers it to the selected six-color palette, and stores the
preview image in `images/`. For each preview, the server also stores a matching
ideal-color display image in `images_display/`; this is the file sent to the
e-ink screen. The generate tab sends a text prompt to the xAI image API using
`XAI_API_KEY` from the environment or `.env`, then dithers the generated image
the same way. The default image model is `grok-imagine-image`; the generate tab
can switch to `grok-imagine-image-pro` for individual requests. It also supports
style transfer: upload a source image in the same form and the server uses xAI
style transfer automatically. Choose `2:3` for portrait or `3:2` for landscape.
The browser preview palette controls how
the image is shown in the web UI. The default calibrated mode dithers using the
ideal Waveshare colors, remaps the browser preview to calibrated display colors,
and sends the ideal-color image to the e-ink screen. The optional mild boost
adds a small contrast, saturation, and sharpness increase before dithering. The
favorites tab lists marked images. The history tab lists all old dithered
images. Both tabs are paginated, can toggle between preview and display-file
views, can mark or unmark favorites, and can send any image to the screen.
When the original source still exists, a history card can open the raw source
image in a new browser tab. Favorites are stored in the local
`image_favorites.json` runtime file. Deleting an item removes the preview image,
matching ideal display image, matching original source file, and any favorite
marker from disk.

Raw source files in `images_raw/` are cleaned automatically when the server
starts if they are older than 30 days. The history tab also has a manual cleanup
button for the same rule. This cleanup does not remove dithered images from
`images/`.

The display path calls `epd.sleep()` in a `finally` block after hardware access
has started. If `epd.sleep()` itself raises, it attempts
`epdconfig.module_exit(cleanup=True)` as a fallback.

### Run at boot with systemd

Create a service file:

```bash
sudo nano /etc/systemd/system/eink-server.service
```

Use this content, replacing `/home/pi/eink_server` and `pi` if your checkout or
username is different:

```ini
[Unit]
Description=E-ink image server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/eink_server
ExecStart=/home/pi/.local/bin/uv run eink-server --host 0.0.0.0 --port 8000
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now eink-server
sudo systemctl status eink-server
```

View logs:

```bash
journalctl -u eink-server -f
```

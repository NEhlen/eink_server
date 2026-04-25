## E-ink image server

Run the webserver with uv:

```bash
uv run python -m backend.server --host 0.0.0.0 --port 8000
```

On a development machine without the Waveshare display attached, use dry-run mode:

```bash
EINK_DRY_RUN=1 uv run python -m backend.server --host 127.0.0.1 --port 8000
```

Open `http://<pi-address>:8000/`. The upload tab stores the original image in
`images_raw/`, crops it to the Waveshare `400x600`/`600x400` aspect ratio,
Floyd-Steinberg dithers it to the six-color palette, and stores the display
image in `images/`. The history tab lists old dithered images and can send any
of them to the screen.

The display path calls `epd.sleep()` in a `finally` block after hardware access
has started. If `epd.sleep()` itself raises, it attempts
`epdconfig.module_exit(cleanup=True)` as a fallback.

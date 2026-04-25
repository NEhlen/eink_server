import logging
import os
import sys
import threading
import time
from pathlib import Path

from PIL import Image

ROOT_DIR = Path(__file__).resolve().parent.parent
LIB_DIR = ROOT_DIR / "lib"

if str(LIB_DIR) not in sys.path:
    sys.path.append(str(LIB_DIR))

logger = logging.getLogger(__name__)
_display_lock = threading.Lock()


def display_image_on_eink(image_path: Path) -> None:
    """
    Display an already-prepared image on the Waveshare panel.

    When hardware has been initialized, epd.sleep() is attempted in the finally
    block even if buffering or display refresh raises.
    """
    image_path = Path(image_path)
    if os.environ.get("EINK_DRY_RUN") == "1":
        with Image.open(image_path) as image:
            logger.info("EINK_DRY_RUN=1: would display %s at %sx%s", image_path, *image.size)
        return

    with _display_lock:
        epd = None
        epdconfig = None
        try:
            from waveshare_epd import epd4in0e
            from waveshare_epd import epdconfig as imported_epdconfig

            epdconfig = imported_epdconfig
            epd = epd4in0e.EPD()
            logger.info("Initializing e-ink display")
            epd.init()

            with Image.open(image_path) as image:
                image.load()
                logger.info("Displaying %s", image_path)
                epd.display(epd.getbuffer(image))
            time.sleep(6)
        finally:
            if epd is not None:
                try:
                    logger.info("Putting e-ink display to sleep")
                    epd.sleep()
                except Exception:
                    logger.exception("epd.sleep() failed")
                    if epdconfig is not None:
                        try:
                            epdconfig.module_exit(cleanup=True)
                        except Exception:
                            logger.exception("Fallback epdconfig.module_exit(cleanup=True) failed")

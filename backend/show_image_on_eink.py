#!/usr/bin/python
# -*- coding:utf-8 -*-
import sys
import os

picdir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "pic"
)
libdir = os.path.join(
    os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "lib"
)
if os.path.exists(libdir):
    sys.path.append(libdir)

import logging
from waveshare_epd import epd4in0e
import time
from PIL import Image, ImageDraw, ImageFont
import traceback

logging.basicConfig(level=logging.DEBUG)

try:
    logging.info("epd4in0e Demo")

    epd = epd4in0e.EPD()
    logging.info("init and Clear")
    epd.init()
    epd.Clear()

    # read bmp file
    logging.info("2.read bmp file")
    Himage = Image.open(os.path.join(picdir, "anime_nibelungen_dith.bmp"))
    # Himage = Himage.transpose(method=Image.Transpose.ROTATE_270)
    # Himage = Himage.resize((epd.width, epd.height))
    epd.display(epd.getbuffer(Himage))
    time.sleep(6)
    # logging.info("Clear...")
    # epd.Clear()

    logging.info("Goto Sleep...")
    epd.sleep()

except IOError as e:
    logging.info(e)

except KeyboardInterrupt:
    logging.info("ctrl + c:")
    epd4in0e.epdconfig.module_exit(cleanup=True)
    exit()

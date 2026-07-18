import os
import sys

if getattr(sys, 'frozen', False):
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.join(sys._MEIPASS, 'ms-playwright')

"""240x135 display with IBM Plex Sans and U Mobile's official logo."""
import time
import board
import displayio
import vectorio
from adafruit_display_text.label import Label
from adafruit_bitmap_font import bitmap_font

ORANGE = 0xF96A1C
WHITE = 0xF2F5F7
MUTED = 0x9AACB9
BG = 0x0C1823


class Screen:
    def __init__(self):
        self.display = board.DISPLAY
        self.display.rotation = 0
        self.fonts = {size: bitmap_font.load_font("/fonts/UsageSans-%d.bdf" % size) for size in (10, 12, 18, 34)}
        self.logo = displayio.OnDiskBitmap("/assets/umobile-logo.bmp")
        self.live = displayio.Group()
        self.setup = displayio.Group()
        for group in (self.live, self.setup):
            self.rect(group, BG, 240, 135, 0, 0)
            group.append(displayio.TileGrid(self.logo, pixel_shader=self.logo.pixel_shader, x=10, y=8))
        self.plan = self.label(self.live, "ULTRA HOME 5G", 64, 9, 12, MUTED)
        self.used = self.label(self.live, "--", 63, 29, 34)
        self.total = self.label(self.live, "of 1,000.00 GB", 64, 65, 12, MUTED)
        self.rect(self.live, 0x273B4A, 220, 5, 10, 85)
        self.progress = self.rect(self.live, ORANGE, 1, 5, 10, 85)
        self.left = self.label(self.live, "Waiting...", 10, 99, 18)
        self.footer = self.label(self.live, "Connecting Wi-Fi", 10, 122, 10, MUTED)
        self.heading = self.label(self.setup, "Starting...", 64, 18, 18)
        self.address = self.label(self.setup, "", 10, 76, 12)
        self.pin_label = self.label(self.setup, "", 10, 97, 18, ORANGE)
        self.setup_footer = self.label(self.setup, "Please keep powered on", 10, 122, 10, MUTED)
        self.display.root_group = self.setup

    @staticmethod
    def rect(group, color, width, height, x, y):
        palette = displayio.Palette(1); palette[0] = color
        rectangle = vectorio.Rectangle(pixel_shader=palette, width=width, height=height, x=x, y=y)
        group.append(rectangle); return rectangle

    def label(self, group, text, x, y, size=12, color=WHITE):
        label = Label(self.fonts[size], text=text, color=color, anchor_point=(0, 0), anchored_position=(x, y))
        group.append(label); return label

    def setup_page(self, heading, address="", pin="", footer="Open address in browser"):
        self.heading.text = heading[:18]
        self.address.text = address[:36]
        self.pin_label.text = "PIN " + pin if pin else ""
        self.setup_footer.text = footer[:36]
        self.display.root_group = self.setup

    def balance(self, snapshot, stale=False):
        self.used.text = "%.2f" % snapshot["usedGB"]
        self.total.text = "of %.2f GB" % snapshot["totalGB"]
        self.left.text = "%.2f GB left" % snapshot["remainingGB"]
        self.progress.width = max(1, min(220, int(220 * snapshot["usedGB"] / snapshot["totalGB"])))
        stamp = time.localtime(snapshot["updatedAt"] + 8 * 3600)
        self.footer.text = ("STALE - retry | " if stale else "Updated ") + "%02d:%02d | 5 min" % (stamp.tm_hour, stamp.tm_min)
        self.display.root_group = self.live

    def layout_bounds(self):
        result = []
        for label in (self.plan, self.used, self.total, self.left, self.footer):
            bx, by, width, height = label.bounding_box
            result.append((label.text, label.x + bx, label.y + by, width, height))
        return result

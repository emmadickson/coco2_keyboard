#!/usr/bin/env python3
"""
coco2_keyboard.py

Scans a TRS-80 Color Computer 2 keyboard matrix wired to a Raspberry Pi 4's
GPIO, and sends the presses to the laptop as USB HID keystrokes via the
/dev/hidg0 gadget device set up by setup_hid_gadget.sh.

Wiring (BCM numbering):
  Columns (outputs)      -> connector pins 9-16
    col0: GPIO5   col1: GPIO6   col2: GPIO13  col3: GPIO19
    col4: GPIO26  col5: GPIO21  col6: GPIO20  col7: GPIO16

  Rows (inputs, pull-up) -> connector pins 1,2,4,5,6,7,8 (pin 3 unused)
    row0: GPIO17  row1: GPIO27  row2: GPIO22  row3: GPIO23
    row4: GPIO24  row5: GPIO25  row6: GPIO12

Run as root (GPIO + /dev/hidg0 access): sudo python3 coco2_keyboard.py
"""

import time
import RPi.GPIO as GPIO

# ---------------------------------------------------------------------------
# Pin configuration
# ---------------------------------------------------------------------------

COLUMN_PINS = [5, 6, 13, 19, 26, 21, 20, 16]      # connector pins 9..16
ROW_PINS = [17, 27, 22, 23, 24, 25, 12]           # connector pins 1,2,4,5,6,7,8

# Row labels match the physical connector pin each row GPIO is wired to,
# for readability only.
ROW_CONNECTOR_PIN = [1, 2, 4, 5, 6, 7, 8]

DEBOUNCE_SEC = 0.02
POLL_SEC = 0.01

# ---------------------------------------------------------------------------
# HID keycodes (USB HID Usage Tables, boot keyboard set)
# ---------------------------------------------------------------------------

HID_A = 0x04
HID_1 = 0x1E
HID_ENTER = 0x28
HID_ESC = 0x29
HID_SPACE = 0x2C
HID_UP = 0x52
HID_DOWN = 0x51
HID_LEFT = 0x50
HID_RIGHT = 0x4F
HID_BACKSPACE = 0x2A
HID_LSHIFT = 0x02  # modifier bit, not a keycode

MOD_LSHIFT = 0x02
MOD_LGUI = 0x08

# key -> (keycode, needs_shift)
KEYCODE = {
    '@': (0x1F, True),  # placeholder; CoCo's '@' varies by layout, adjust after testing
    'A': (0x04, False), 'B': (0x05, False), 'C': (0x06, False), 'D': (0x07, False),
    'E': (0x08, False), 'F': (0x09, False), 'G': (0x0A, False), 'H': (0x0B, False),
    'I': (0x0C, False), 'J': (0x0D, False), 'K': (0x0E, False), 'L': (0x0F, False),
    'M': (0x10, False), 'N': (0x11, False), 'O': (0x12, False), 'P': (0x13, False),
    'Q': (0x14, False), 'R': (0x15, False), 'S': (0x16, False), 'T': (0x17, False),
    'U': (0x18, False), 'V': (0x19, False), 'W': (0x1A, False), 'X': (0x1B, False),
    'Y': (0x1C, False), 'Z': (0x1D, False),
    '0': (0x27, False), '1!': (0x1E, False), '2"': (0x1F, False), '3#': (0x20, False),
    '4$': (0x21, False), '5%': (0x22, False), '6&': (0x23, False), '7\'': (0x24, False),
    '8(': (0x25, False), '9)': (0x26, False), ':*': (0x33, True), ';+': (0x33, False),
    ',<': (0x36, False), '-=': (0x2D, False), '.>': (0x37, False), '/?': (0x38, False),
    'UP': (HID_UP, False), 'DWN': (HID_DOWN, False), 'LFT': (HID_BACKSPACE, False),
    'RGT': (HID_RIGHT, False), 'SPACE': (HID_SPACE, False),
    'ENT': (HID_ENTER, False), 'CLR': (None, False), 'BRK': (HID_ESC, False),
    'SHIFT': (None, False),  # handled as a modifier, not a keystroke
    'COMMAND': (None, False),  # CLR repurposed as Command modifier
}

# ---------------------------------------------------------------------------
# Matrix -> key label, from the CoCo2 connector diagram
# rows: connector pins 1,2,4,5,6,7,8  (index 0..6 here)
# cols: connector pins 9-16           (index 0..7 here)
# ---------------------------------------------------------------------------

MATRIX_KEYS = [
    ['@', 'A', 'B', 'C', 'D', 'E', 'F', 'G'],            # row pin 1
    ['H', 'I', 'J', 'K', 'L', 'M', 'N', 'O'],            # row pin 2
    ['P', 'Q', 'R', 'S', 'T', 'U', 'V', 'W'],            # row pin 4
    ['X', 'Y', 'Z', 'UP', 'DWN', 'LFT', 'RGT', 'SPACE'], # row pin 5
    ['0', '1!', '2"', '3#', '4$', '5%', '6&', '7\''],    # row pin 6
    ['8(', '9)', ':*', ';+', ',<', '-=', '.>', '/?'],    # row pin 7
    ['ENT', 'CLR', 'BRK', None, None, None, None, 'SHIFT'],  # row pin 8 (CoCo2: no Alt/Ctrl/F1/F2)
]

# ---------------------------------------------------------------------------
# GPIO setup
# ---------------------------------------------------------------------------

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in COLUMN_PINS:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.HIGH)  # idle high; we pull each low in turn
    for pin in ROW_PINS:
        GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)


def scan_matrix():
    """Returns a set of (row_index, col_index) currently pressed."""
    pressed = set()
    for col_index, col_pin in enumerate(COLUMN_PINS):
        GPIO.output(col_pin, GPIO.LOW)
        time.sleep(0.0005)  # let the line settle
        for row_index, row_pin in enumerate(ROW_PINS):
            if GPIO.input(row_pin) == GPIO.LOW:
                pressed.add((row_index, col_index))
        GPIO.output(col_pin, GPIO.HIGH)
    return pressed


# ---------------------------------------------------------------------------
# HID output
# ---------------------------------------------------------------------------

def send_hid_report(hidg, modifier, keycode):
    """Writes one 8-byte boot-keyboard HID report."""
    report = bytearray(8)
    report[0] = modifier
    if keycode:
        report[2] = keycode
    hidg.write(bytes(report))
    hidg.flush()


def release_all(hidg):
    send_hid_report(hidg, 0, 0)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    setup_gpio()
    prev_pressed = set()

    with open('/dev/hidg0', 'rb+') as hidg:
        print("CoCo2 keyboard bridge running. Ctrl+C to stop.")
        try:
            while True:
                pressed = scan_matrix()

                if pressed != prev_pressed:
                    newly_pressed = pressed - prev_pressed
                    for (row_i, col_i) in newly_pressed:
                        label = MATRIX_KEYS[row_i][col_i]
                        if label and label not in ('SHIFT', 'CLR'):
                            shift_held = any(
                                MATRIX_KEYS[r][c] == 'SHIFT' for (r, c) in pressed
                            )
                            command_held = any(
                                MATRIX_KEYS[r][c] == 'CLR' for (r, c) in pressed
                            )
                            space_held = any(
                                MATRIX_KEYS[r][c] == 'SPACE' for (r, c) in pressed
                            )
                            # Shift+Space acts as an extra Command trigger (for
                            # macOS screenshot shortcuts like Cmd+Shift+4).
                            # Don't fire Space's own keystroke in that case.
                            if label == 'SPACE' and shift_held:
                                continue
                            entry = KEYCODE.get(label)
                            if entry:
                                keycode, needs_shift = entry
                                modifier = 0
                                if needs_shift or shift_held:
                                    modifier |= MOD_LSHIFT
                                if command_held or (shift_held and space_held):
                                    modifier |= MOD_LGUI
                                send_hid_report(hidg, modifier, keycode)
                                time.sleep(DEBOUNCE_SEC)
                                release_all(hidg)
                    if not pressed:
                        release_all(hidg)

                prev_pressed = pressed
                time.sleep(POLL_SEC)
        except KeyboardInterrupt:
            pass
        finally:
            release_all(hidg)
            GPIO.cleanup()


if __name__ == '__main__':
    main()

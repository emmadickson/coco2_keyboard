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
HID_TAB = 0x2B
HID_ENTER = 0x28
HID_ESC = 0x29
HID_SPACE = 0x2C
HID_UP = 0x52
HID_DOWN = 0x51
HID_LEFT = 0x50
HID_RIGHT = 0x4F
HID_BACKSPACE = 0x2A

MOD_LSHIFT = 0x02
MOD_LGUI = 0x08

# ---------------------------------------------------------------------------
# Key mapping
#
# The host applies a US layout to whatever we send, and several of the CoCo's
# shifted characters sit on *different* physical keys in US layout. So Shift
# cannot simply be passed through -- each key gets an explicit unshifted and
# shifted target.
#
#   label -> ((keycode, modifier) unshifted, (keycode, modifier) shifted)
#
# The modifier here is what a US host needs to produce the character printed
# on the CoCo keycap, not the state of the CoCo's own Shift key.
# ---------------------------------------------------------------------------


def _letter(ch):
    """Letters: same keycode both ways, Shift just capitalizes."""
    code = HID_A + (ord(ch) - ord('A'))
    return ((code, 0), (code, MOD_LSHIFT))


KEYCODE = {
    #  label        unshifted              shifted            CoCo cap  (US source)
    '@':  ((0x1F, MOD_LSHIFT), (0x1F, MOD_LSHIFT)),        # @   @      shift+2
    '0':  ((0x27, 0),          (0x27, 0)),                 # 0   -      no shifted char
    '1!': ((0x1E, 0),          (0x1E, MOD_LSHIFT)),        # 1   !      shift+1
    '2"': ((0x1F, 0),          (0x34, MOD_LSHIFT)),        # 2   "      shift+'
    '3#': ((0x20, 0),          (0x20, MOD_LSHIFT)),        # 3   #      shift+3
    '4$': ((0x21, 0),          (0x21, MOD_LSHIFT)),        # 4   $      shift+4
    '5%': ((0x22, 0),          (0x22, MOD_LSHIFT)),        # 5   %      shift+5
    '6&': ((0x23, 0),          (0x24, MOD_LSHIFT)),        # 6   &      shift+7
    "7'": ((0x24, 0),          (0x34, 0)),                 # 7   '      bare '
    '8(': ((0x25, 0),          (0x26, MOD_LSHIFT)),        # 8   (      shift+9
    '9)': ((0x26, 0),          (0x27, MOD_LSHIFT)),        # 9   )      shift+0
    ':*': ((0x33, MOD_LSHIFT), (0x25, MOD_LSHIFT)),        # :   *      shift+; / shift+8
    '-=': ((0x2D, 0),          (0x2E, 0)),                 # -   =      bare =
    ';+': ((0x33, 0),          (0x2E, MOD_LSHIFT)),        # ;   +      shift+=
    ',<': ((0x36, 0),          (0x36, MOD_LSHIFT)),        # ,   <      shift+,
    '.>': ((0x37, 0),          (0x37, MOD_LSHIFT)),        # .   >      shift+.
    '/?': ((0x38, 0),          (0x38, MOD_LSHIFT)),        # /   ?      shift+/

    'UP':    ((HID_UP, 0),        (HID_TAB, 0)),  # Shift+Up -> Tab
    'DWN':   ((HID_DOWN, 0),      (HID_DOWN, MOD_LSHIFT)),
    'LFT':   ((HID_BACKSPACE, 0), (HID_BACKSPACE, MOD_LSHIFT)),
    'RGT':   ((HID_RIGHT, 0),     (HID_RIGHT, MOD_LSHIFT)),
    'SPACE': ((HID_SPACE, 0),     (HID_SPACE, MOD_LSHIFT)),
    'ENT':   ((HID_ENTER, 0),     (HID_ENTER, MOD_LSHIFT)),
    'BRK':   ((HID_ESC, 0),       (HID_ESC, MOD_LSHIFT)),

    'CLR':     None,  # repurposed as the Command modifier
    'SHIFT':   None,  # handled as a modifier, not a keystroke
    'COMMAND': None,
}

KEYCODE.update({ch: _letter(ch) for ch in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'})

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
    ['0', '1!', '2"', '3#', '4$', '5%', '6&', "7'"],     # row pin 6
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


def resolve(label, shift_held, gui_held):
    """Returns (keycode, modifier) for a key press, or None if it emits nothing."""
    entry = KEYCODE.get(label)
    if not entry:
        return None

    unshifted, shifted = entry

    if gui_held:
        # Shortcuts key off physical keys, not printed characters, so send the
        # base keycode and let Shift ride along as a plain modifier. Otherwise
        # Cmd+Shift+4 would go out as Cmd+Shift+$-on-some-other-key.
        keycode, modifier = unshifted
        if shift_held:
            modifier |= MOD_LSHIFT
        modifier |= MOD_LGUI
    else:
        keycode, modifier = shifted if shift_held else unshifted

    return keycode, modifier


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
                    gui_held = command_held or (shift_held and space_held)

                    for (row_i, col_i) in newly_pressed:
                        label = MATRIX_KEYS[row_i][col_i]
                        if not label or label in ('SHIFT', 'CLR'):
                            continue
                        # Don't fire Space's own keystroke when it's acting
                        # as the Command trigger.
                        if label == 'SPACE' and shift_held:
                            continue
                        result = resolve(label, shift_held, gui_held)
                        if result:
                            keycode, modifier = result
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

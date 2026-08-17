#!/bin/bash
# setup_hid_gadget.sh
# One-time (per boot) setup of a USB HID keyboard gadget on a Raspberry Pi 4.
# Run as root: sudo ./setup_hid_gadget.sh
#
# Prerequisites (edit these once, then reboot, before running this script):
#   /boot/firmware/config.txt   -> add line: dtoverlay=dwc2,dr_mode=peripheral
#   /boot/firmware/cmdline.txt  -> add "modules-load=dwc2" right after "rootwait"
#                                   (keep the whole file on one physical line)

set -e

GADGET_DIR=/sys/kernel/config/usb_gadget/coco2kbd

if [ -d "$GADGET_DIR" ]; then
    echo "Gadget already exists at $GADGET_DIR, skipping creation."
else
    mkdir -p "$GADGET_DIR"
    cd "$GADGET_DIR"

    echo 0x1d6b > idVendor    # Linux Foundation
    echo 0x0104 > idProduct   # Multifunction Composite Gadget
    echo 0x0100 > bcdDevice
    echo 0x0200 > bcdUSB

    mkdir -p strings/0x409
    echo "0123456789" > strings/0x409/serialnumber
    echo "CoCo2 Project" > strings/0x409/manufacturer
    echo "CoCo2 USB Keyboard" > strings/0x409/product

    mkdir -p configs/c.1/strings/0x409
    echo "Config 1: HID keyboard" > configs/c.1/strings/0x409/configuration
    echo 250 > configs/c.1/MaxPower

    mkdir -p functions/hid.usb0
    echo 1 > functions/hid.usb0/protocol
    echo 1 > functions/hid.usb0/subclass
    echo 8 > functions/hid.usb0/report_length
    # Standard boot-keyboard HID report descriptor (8-byte reports:
    # 1 modifier byte, 1 reserved byte, 6 keycode bytes)
    echo -ne \\x05\\x01\\x09\\x06\\xa1\\x01\\x05\\x07\\x19\\xe0\\x29\\xe7\\x15\\x00\\x25\\x01\\x75\\x01\\x95\\x08\\x81\\x02\\x95\\x01\\x75\\x08\\x81\\x03\\x95\\x05\\x75\\x01\\x05\\x08\\x19\\x01\\x29\\x05\\x91\\x02\\x95\\x01\\x75\\x03\\x91\\x03\\x95\\x06\\x75\\x08\\x15\\x00\\x25\\x65\\x05\\x07\\x19\\x00\\x29\\x65\\x81\\x00\\xc0 \
      > functions/hid.usb0/report_desc

    ln -s functions/hid.usb0 configs/c.1/

    UDC_DEVICE=$(ls /sys/class/udc | head -n 1)
    if [ -z "$UDC_DEVICE" ]; then
        echo "ERROR: no UDC device found. Is dwc2 loaded in peripheral mode?"
        exit 1
    fi
    echo "$UDC_DEVICE" > UDC

    echo "Gadget activated on UDC: $UDC_DEVICE"
fi

echo "Waiting for /dev/hidg0..."
for i in $(seq 1 10); do
    if [ -e /dev/hidg0 ]; then
        echo "/dev/hidg0 is ready."
        exit 0
    fi
    sleep 0.5
done

echo "WARNING: /dev/hidg0 did not appear. Check that the Pi's USB-C port"
echo "is plugged into the laptop with a DATA cable (not charge-only),"
echo "and check 'dmesg' for dwc2/UDC errors."

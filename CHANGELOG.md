# Changelog

## 0.4.0
- Preview camera on each device: a still image from the camera so you can tell cameras apart, refreshed at most every 10 seconds. Uses the camera's own snapshot command, falling back to a frame from the RTSP substream. Opening it gives the live substream.
- New cameras are named after the camera's own name (e.g. "Front drive (192.168.1.20)") instead of the chip model.

## 0.3.1
- Integration icon (shown on Home Assistant 2026.3 and later).

## 0.3.0
- Search the network for cameras when adding one, with an optional subnet sweep for cameras on another VLAN.
- Background broadcast discovery every 30 minutes; new cameras appear under Discovered.

## 0.2.0
- Capability-driven: controls are only created for settings each camera actually has.
- Multi-channel support.
- Picture, camera name, motion/tamper detection, network, IP allow list and scheduled reboot controls.
- Diagnostics download.

## 0.1.0
- First version: stream encoding, overlays, cloud and NTP settings, reboot and clock buttons, raw get/set actions.

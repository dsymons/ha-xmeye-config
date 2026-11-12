# XMEye Camera Config

Home Assistant integration for configuring Xiongmai-based cameras (XMEye, iCSee,
NetSurveillance, "VideoPlayTool" web viewer) locally over the DVRIP protocol on
port 34567. No plugin, cloud account or extra Python packages needed.

It configures cameras; it doesn't provide video. Keep streaming through
Frigate/go2rtc. For PTZ and motion-alarm entities, use
[icsee-ptz](https://github.com/dbuezas/icsee-ptz) alongside it.

## Finding cameras
**Add integration → XMEye Camera Config → Search the network** sends the
cameras' own search broadcast (UDP 34569) and lists every camera that answers.
Broadcasts don't cross VLANs, so if your cameras are on a different subnet
from Home Assistant, type that subnet (e.g. `192.168.10.0/24`) in the search
form: it then also probes each address for the DVRIP port and lists the
cameras it finds. Cameras you've already added are left out.

Once one camera is set up, Home Assistant repeats the broadcast search at
start-up and every 30 minutes; any new camera appears under
**Settings → Devices & services → Discovered**, ready to add with its password.
Ignore a card to stop it reappearing.

Home Assistant needs to receive UDP on port 34569 for the broadcast search
(automatic on Home Assistant OS and host-network Docker).

## How it adapts to each camera
On setup the integration asks the camera which config sections it has and how
many channels it reports. A control is only created when the camera returns a
value of the expected type for it, so each model gets exactly the controls its
firmware supports. Multi-channel devices get one set per channel. Unknown
values (for example an unusual day/night mode) are still shown and kept
selectable rather than hidden.

Every control comes from one line in `catalog.py`. To support a new setting,
add a `Field` there (section, path, type, range) — no other code needed.

## Install

### HACS (recommended)
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/dsymons/ha-xmeye-config`,
   category **Integration**.
2. Search for **XMEye Camera Config**, download it, and restart Home Assistant.
3. **Settings → Devices & services → Add integration → XMEye Camera Config**.

Updates then show up in HACS whenever a new release is published.

### Manual
Copy `custom_components/xmeye_config` to `/config/custom_components/` (or unzip
`xmeye_config.zip` from a release there), restart Home Assistant, then add the
integration as above. Enter the camera IP, port 34567, `admin` and the password
(blank if none). Add one entry per camera.

## Controls (only where the camera supports them)
| Area | Controls |
|---|---|
| Streams (main / sub) | resolution, codec, bitrate mode, frame rate, bitrate, keyframe interval, quality, audio, substream on/off |
| Overlays & identity | timestamp overlay, camera name overlay, camera name text |
| Picture | brightness, contrast, saturation, hue*, flip, mirror, day/night mode, anti-flicker, backlight compensation, WDR + level, prevent overexposure, defog + level, exposure sensitivity and target, day/night noise reduction, day/night threshold*, IR-cut swap* |
| Detection | camera motion detection + sensitivity, tamper detection + sensitivity |
| Network | cloud connection (XMEye), UPnP, mobile service*, NTP sync + server, hostname, IP allow list + addresses; diagnostic sensors for IP, gateway, MAC, DHCP, netmask*, DNS*, ports* |
| Maintenance | scheduled reboot day and hour, reboot button, set clock from Home Assistant |

\* disabled by default; enable from the entity list if wanted.

**IP allow list safety:** the switch refuses to turn on unless Home Assistant's
own address is in the allow list, and the address list can't drop Home
Assistant while the list is on.

## New camera? Download diagnostics
Device page → ⋮ → **Download diagnostics** gives every section the camera
reports, including ones the integration doesn't use yet, plus its capability
reports. Passwords, serial numbers and MACs are redacted. Use it to add fields
to `catalog.py`.

## Services for anything else
- `xmeye_config.get_config` — read any section or capability (`kind: ability`).
- `xmeye_config.set_config` — write a full section back (read it first, edit,
  send the whole value).

## Publishing a new version
1. Bump `version` in `custom_components/xmeye_config/manifest.json` and add a
   `CHANGELOG.md` entry.
2. Commit and push to `main`; the Validate workflow runs HACS, hassfest and the tests.
3. Create a GitHub release tagged `v<version>` (e.g. `v0.3.1`). The Release
   workflow checks the tag matches the manifest and attaches `xmeye_config.zip`.
   HACS offers the update to every install.

## Tests
`pip install -r requirements_test.txt && pytest tests` runs against simulated cameras: a full-featured single-channel
model, a basic one, and a sparse two-channel one.

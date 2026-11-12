"""Constants for XMEye Camera Config."""

DOMAIN = "xmeye_config"
DEFAULT_PORT = 34567
DEFAULT_USERNAME = "admin"
SCAN_INTERVAL_SECONDS = 300

# Xiongmai SDK capture-size enum, in bit order of the ResolutionMask in
# EncodeCapability. Only trusted when it decodes the camera's current value.
RESOLUTION_BITS = [
    "D1", "HD1", "BCIF", "CIF", "QCIF", "VGA", "QVGA", "SVCD", "QQVGA", "ND1",
    "960H", "720P", "960", "SXGA", "1080P", "UXGA", "WUXGA", "2_5M", "3M", "5M",
    "1080N", "4M", "6M", "8M", "12M", "4K", "720N", "WSVGA", "NHD", "3M_N",
    "4M_N", "5M_N",
]

# Fallback choices when the capability query is unavailable.
FALLBACK_RESOLUTIONS = {
    "MainFormat": ["720P", "960", "1080P", "3M", "4M", "5M", "4K"],
    "ExtraFormat": ["QVGA", "CIF", "VGA", "D1", "HD1", "720P"],
}

ATTR_NAME = "name"
ATTR_DATA = "data"
ATTR_KIND = "kind"
ATTR_CONFIG_ENTRY = "config_entry_id"

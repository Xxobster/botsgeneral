"""VPS aliases shared by agent and hub (no report/collect imports)."""

VPS_ALIASES = {
    "94.156.189.76": "ln1",
    "212.73.150.178": "ln2",
    "185.203.119.52": "ln3",
    "212.73.150.149": "sm",
}


def vps_alias(vps_id: str | None) -> str:
    if not vps_id:
        return "unknown"
    return VPS_ALIASES.get(str(vps_id), str(vps_id))

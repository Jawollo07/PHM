SERVER_STATUS_LABELS = {
    "pending": "Ausstehend",
    "provisioning": "Wird bereitgestellt",
    "installing": "Wird installiert",
    "installed": "Aktiv",
    "failed": "Fehlgeschlagen",
}


def server_resource_details(resource_limits):
    if not isinstance(resource_limits, dict):
        return []
    pelican_config = resource_limits.get("pelican")
    if not isinstance(pelican_config, dict):
        return []

    details = []
    limits = pelican_config.get("limits", {})
    if isinstance(limits, dict):
        for key, label, unit in (
            ("memory", "Arbeitsspeicher", "MB"),
            ("swap", "Swap", "MB"),
            ("disk", "Speicherplatz", "MB"),
            ("cpu", "CPU-Limit", "%"),
            ("io", "I/O-Gewichtung", ""),
        ):
            value = limits.get(key)
            if type(value) is int:
                suffix = unit if unit == "%" else (f" {unit}" if unit else "")
                display_value = (
                    "Unbegrenzt"
                    if key == "swap" and value == -1
                    else f"{value:,}".replace(",", ".") + suffix
                )
                details.append({"label": label, "value": display_value})

    feature_limits = pelican_config.get("feature_limits", {})
    if isinstance(feature_limits, dict):
        for key, label in (
            ("databases", "Datenbanken"),
            ("allocations", "Zusätzliche Ports"),
            ("backups", "Backups"),
        ):
            value = feature_limits.get(key)
            if type(value) is int:
                details.append({"label": label, "value": str(value)})

    return details


def server_status_label(status):
    return SERVER_STATUS_LABELS.get(status, status)

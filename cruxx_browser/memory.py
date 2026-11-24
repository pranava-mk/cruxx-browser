"""WebKit memory pressure limits for the web processes."""

import logging

log = logging.getLogger(__name__)
MIN_MB = 512
MAX_MB = 4096
_done = False


def limit_mb(total_kb):
    """Return the memory limit in MB: 25% of RAM, between MIN_MB and MAX_MB."""
    return max(MIN_MB, min(MAX_MB, int(total_kb) // 1024 // 4))


def total_ram_kb(path="/proc/meminfo"):
    try:
        with open(path, "r", encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def apply(WebKit2):
    """Set the limits once, before any web process starts. Skip if not supported."""
    global _done
    if _done:
        return
    _done = True
    if not hasattr(WebKit2, "MemoryPressureSettings"):
        log.debug("memory pressure settings not available")
        return
    setter = getattr(WebKit2.WebsiteDataManager, "set_memory_pressure_settings", None)
    if setter is None:
        log.debug("memory pressure setter not available")
        return
    total = total_ram_kb()
    if not total:
        log.debug("RAM size unknown: memory limit not set")
        return
    settings = WebKit2.MemoryPressureSettings.new()
    settings.set_memory_limit(limit_mb(total))
    # Set strict first: conservative must stay below it.
    settings.set_strict_threshold(0.75)
    settings.set_conservative_threshold(0.5)
    settings.set_kill_threshold(0.0)
    settings.set_poll_interval(30.0)
    setter(settings)
    log.debug("memory limit set to %d MB", limit_mb(total))

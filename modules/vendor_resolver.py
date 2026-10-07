# -*- coding: utf-8 -*-

from pathlib import Path
from threading import RLock


class VendorResolver:
    """Lokale, gecachte MAC-/OUI-Herstellererkennung."""

    IEEE_DATABASE_PATHS = (
        Path("/usr/share/ieee-data/oui.txt"),
        Path("/var/lib/ieee-data/oui.txt"),
    )

    OVERRIDE_PATH = Path("/etc/server-manager/mac-vendors.conf")

    def __init__(self):
        self._lock = RLock()
        self._loaded = False
        self._vendors = {}
        self._overrides = {}
        self._source = ""
        self._load_error = ""

    @staticmethod
    def normalize_mac(value):
        return (
            str(value or "")
            .strip()
            .upper()
            .replace(":", "")
            .replace("-", "")
            .replace(".", "")
        )

    @staticmethod
    def _valid_key(value):
        return len(value) in (6, 12) and all(
            char in "0123456789ABCDEF"
            for char in value
        )

    def _load_ieee_database(self):
        vendors = {}
        loaded_path = ""

        seen_paths = set()

        for path in self.IEEE_DATABASE_PATHS:
            try:
                resolved = str(path.resolve())
            except Exception:
                resolved = str(path)

            if resolved in seen_paths:
                continue

            seen_paths.add(resolved)

            if not path.is_file():
                continue

            try:
                with path.open(
                    "r",
                    encoding="utf-8",
                    errors="replace",
                ) as handle:
                    for line in handle:
                        if "(base 16)" not in line:
                            continue

                        prefix_part, vendor_part = line.split(
                            "(base 16)",
                            1,
                        )

                        prefix = self.normalize_mac(prefix_part)
                        vendor = vendor_part.strip()

                        if len(prefix) == 6 and vendor:
                            vendors[prefix] = vendor

                if vendors:
                    loaded_path = str(path)
                    break

            except Exception as exc:
                self._load_error = (
                    f"{path}: {exc}"
                )

        return vendors, loaded_path

    def _load_overrides(self):
        overrides = {}

        if not self.OVERRIDE_PATH.is_file():
            return overrides

        try:
            with self.OVERRIDE_PATH.open(
                "r",
                encoding="utf-8",
                errors="replace",
            ) as handle:
                for raw_line in handle:
                    line = raw_line.strip()

                    if not line or line.startswith("#"):
                        continue

                    if "=" not in line:
                        continue

                    key, vendor = line.split("=", 1)

                    key = self.normalize_mac(key)
                    vendor = vendor.strip()

                    if (
                        self._valid_key(key)
                        and vendor
                    ):
                        overrides[key] = vendor

        except Exception as exc:
            self._load_error = (
                f"{self.OVERRIDE_PATH}: {exc}"
            )

        return overrides

    def load(self, force=False):
        with self._lock:
            if self._loaded and not force:
                return

            self._load_error = ""

            vendors, source = self._load_ieee_database()
            overrides = self._load_overrides()

            self._vendors = vendors
            self._overrides = overrides
            self._source = source
            self._loaded = True

    def reload(self):
        self.load(force=True)

        return self.status()

    def lookup(self, mac):
        normalized = self.normalize_mac(mac)

        if len(normalized) < 6:
            return ""

        self.load()

        with self._lock:
            # Exakte MAC-Overrides haben Vorrang.
            if len(normalized) >= 12:
                exact = normalized[:12]

                if exact in self._overrides:
                    return self._overrides[exact]

            prefix = normalized[:6]

            # Danach OUI-Overrides.
            if prefix in self._overrides:
                return self._overrides[prefix]

            return self._vendors.get(prefix, "")

    def status(self):
        self.load()

        with self._lock:
            return {
                "loaded": self._loaded,
                "vendors": len(self._vendors),
                "overrides": len(self._overrides),
                "source": self._source,
                "override_path": str(self.OVERRIDE_PATH),
                "error": self._load_error,
            }


vendor_resolver = VendorResolver()


def vendor_from_mac(mac):
    return vendor_resolver.lookup(mac)


def reload_vendor_cache():
    return vendor_resolver.reload()


def vendor_resolver_status():
    return vendor_resolver.status()

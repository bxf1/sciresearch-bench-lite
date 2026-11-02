"""Predeclared diagnostic profiles; never mounted into researcher containers."""

PROFILES = {
    "heat": ("amplitude", "spectral_decay", "contiguous_mask"),
    "ode": ("coordinate_scale", "coordinate_swap", "stable_cubic"),
    "poisson": ("large_grid", "five_disks", "cache_order"),
}
SPLITS = ("diagnostic-calibration", "diagnostic-test")


def specifications(task):
    rows = []
    for profile in PROFILES[task]:
        for index in range(4):
            level = 1 + index % 2
            options = {}
            if task == "heat":
                if profile == "amplitude":
                    options[profile] = (.5, 2.)[index // 2]
                elif profile == "spectral_decay":
                    options[profile] = (1., 3.)[index // 2]
                else:
                    options[profile] = True
            elif task == "ode":
                options["profile"] = profile
            else:
                options["n"] = 256 if profile == "large_grid" else 128
                if profile == "five_disks":
                    options["disks"] = 5
                if profile == "cache_order":
                    options["cache_order"] = True
            rows.append({"profile_id": profile, "profile_index": index,
                         "level": level, "options": options})
    return rows

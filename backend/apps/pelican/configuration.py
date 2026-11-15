class PelicanConfigurationError(Exception):
    """A safe, stable validation error for catalog-side Pelican settings."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def validate_pelican_configuration(resource_limits):
    """Validate and return the Pelican section of a catalog resource snapshot."""
    if not isinstance(resource_limits, dict):
        raise PelicanConfigurationError("invalid_plan_resources")

    config = resource_limits.get("pelican")
    if not isinstance(config, dict):
        raise PelicanConfigurationError("pelican_config_missing")

    for key in ("egg_id", "allocation_id"):
        if type(config.get(key)) is not int or config[key] < 1:
            raise PelicanConfigurationError(f"invalid_{key}")

    limits = config.get("limits")
    feature_limits = config.get("feature_limits")
    environment = config.get("environment", {})
    if not isinstance(limits, dict) or not isinstance(feature_limits, dict) or not isinstance(environment, dict):
        raise PelicanConfigurationError("invalid_plan_resources")

    required_limits = ("memory", "swap", "disk", "io", "cpu")
    required_features = ("databases", "allocations", "backups")
    if any(type(limits.get(key)) is not int for key in required_limits):
        raise PelicanConfigurationError("invalid_resource_limits")
    if any(type(feature_limits.get(key)) is not int for key in required_features):
        raise PelicanConfigurationError("invalid_feature_limits")
    if (limits["memory"] < 0 or limits["disk"] < 0 or limits["swap"] < -1
            or not 0 <= limits["io"] <= 1000 or limits["cpu"] < 0):
        raise PelicanConfigurationError("invalid_resource_limits")
    if any(feature_limits[key] < 0 for key in required_features):
        raise PelicanConfigurationError("invalid_feature_limits")
    if "threads" in limits and limits["threads"] is not None and not isinstance(limits["threads"], str):
        raise PelicanConfigurationError("invalid_resource_limits")
    if any(not isinstance(key, str) or not key
           or not isinstance(value, (str, int, float, bool))
           for key, value in environment.items()):
        raise PelicanConfigurationError("invalid_environment")

    for flag in ("skip_scripts", "oom_disabled", "start_on_completion"):
        if flag in config and type(config[flag]) is not bool:
            raise PelicanConfigurationError("invalid_egg_configuration")
    docker_image = config.get("docker_image")
    startup = config.get("startup")
    if (not isinstance(docker_image, str) or not docker_image.strip()
            or not isinstance(startup, str) or not startup.strip()):
        raise PelicanConfigurationError("invalid_egg_configuration")
    return config

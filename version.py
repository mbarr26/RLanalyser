"""The app's version, shown in the title bar and used to name the installer."""

APP_VERSION = "1.1.0"

# Where the app looks for a newer release: the address of a `latest.json` manifest (an https URL,
# or a local/network folder or file). Empty until there is a website to host it. A user can
# override it with "update_url" in config.json, and tests with the RLA_UPDATE_URL env var.
UPDATE_URL = ""

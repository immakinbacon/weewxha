"""WeeWX extension installer for the weewxha skin.

Installs with either CLI, depending on your WeeWX version:

    weectl extension install /path/to/weewxha      # WeeWX 5.x
    wee_extension --install /path/to/weewxha        # WeeWX 4.x

This installs the WeeWX skin under skins/weewxha and its supporting Python
modules under bin/user. It does not touch custom_components/weewxha -- that
half is a Home Assistant custom integration, installed separately (see
README.md).
"""

from weecfg.extension import ExtensionInstaller


def loader():
    return WeewxHaInstaller()


class WeewxHaInstaller(ExtensionInstaller):
    def __init__(self):
        super(WeewxHaInstaller, self).__init__(
            version="0.5.0",
            name="weewxha",
            description="Dashboard skin and JSON data feed for the weewxha Home Assistant integration",
            author="",
            author_email="",
            config={
                "StdReport": {
                    "weewxha": {
                        "skin": "weewxha",
                        "HTML_ROOT": "weewxha",
                        "enable": "true",
                    }
                }
            },
            files=[
                # The search list extension is referenced from skin.conf as
                # "user.weewxha_search", so it has to land in WeeWX's user
                # package directory -- not alongside the templates, which
                # aren't on the Python path.
                (
                    "bin/user",
                    [
                        "bin/user/weewxha_search.py",
                        "bin/user/weewxha_forecast.py",
                        "bin/user/weewxha_ha.py",
                        "bin/user/weewxha_nws.py",
                        "bin/user/weewxha_chart.py",
                        "bin/user/weewxha_icons.py",
                        "bin/user/weewxha_history.py",
                    ],
                ),
                (
                    "skins/weewxha",
                    [
                        "skins/weewxha/skin.conf",
                        "skins/weewxha/index.html.tmpl",
                        "skins/weewxha/weewxha.json.tmpl",
                    ],
                ),
                (
                    "skins/weewxha/static",
                    [
                        "skins/weewxha/static/weewxha.css",
                    ],
                ),
            ],
        )

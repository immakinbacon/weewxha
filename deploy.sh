#!/usr/bin/env bash
#
# Deploy the weewxha skin to a WeeWX host.
#
# Packages the committed tree with `git archive` and installs it as a WeeWX
# extension, locally or over SSH. The Home Assistant custom_components half is
# NOT deployed by this script -- that lives on your Home Assistant host and is
# installed separately (see README.md).
#
#   ./deploy.sh                              # install on this machine
#   ./deploy.sh --host pi@weather.local      # install on a remote WeeWX host
#   ./deploy.sh --host pi@weather.local -n   # show what would happen
#
# Your weewx.conf is safe: WeeWX merges the extension's config stanza with
# `conditional_merge`, which only fills in keys that don't already exist, so
# reinstalling never overwrites your unit or forecast settings. (`--clean` is
# the exception; see below.)
#
# Authentication: every scp/ssh shares one multiplexed connection, so a remote
# deploy asks for your SSH credentials once. If WeeWX on the far end is
# root-owned, sudo asks for a password once more; to avoid that, either use
# --no-sudo (for a user-owned WeeWX) or give the deploying user a NOPASSWD
# sudoers rule for weectl and systemctl.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

HOST=""
REF="HEAD"
SERVICE="weewx"
CONFIG=""
VERIFY_URL=""
DRY_RUN=0
RESTART=1
CLEAN=0
CONFIGURE=0
SUDO_MODE="auto"

usage() {
    # The header comment block, minus the shebang, is the help text.
    awk 'NR>2 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
    cat <<'EOF'

Options:
  -H, --host USER@HOST   Deploy over SSH instead of to this machine.
  -r, --ref REF          Git ref to deploy. Default: HEAD.
  -c, --config PATH      Path to weewx.conf, if weectl can't find it itself.
  -s, --service NAME     systemd service to restart. Default: weewx.
  -u, --url URL          After deploying, fetch this URL and check the feed
                         parses and contains a forecast.
  -C, --configure        Ask for the skin's settings (units, forecast, and
                         the optional Home Assistant pressure source, incl.
                         its TLS handling) and write them into weewx.conf
                         after installing. Secrets
                         go into mode-600 files beside weewx.conf, never into
                         weewx.conf itself. Press Enter at any prompt to keep
                         the current value.
  -n, --dry-run          Show every step without changing anything.
      --sudo             Always run the install as root via sudo.
      --no-sudo          Never use sudo. Default is to decide by whether
                         weewx.conf is writable by you.
      --no-restart       Install but leave the running WeeWX alone. The new
                         skin takes effect at the next report cycle.
      --clean            Uninstall the existing extension first, clearing any
                         files left behind by older versions. Note: WeeWX's
                         uninstall removes the stanza's own settings (skin,
                         HTML_ROOT, enable) and the reinstall puts them back
                         at their defaults -- so a customised HTML_ROOT is
                         reset. Nested [[[Units]]] and [[[Forecast]]] sections
                         survive. WeeWX backs up weewx.conf either way.
  -h, --help             This message.
EOF
}

die() { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }
step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }

while [ $# -gt 0 ]; do
    case "$1" in
        -H|--host)    HOST="${2:?--host needs a value}"; shift 2 ;;
        -r|--ref)     REF="${2:?--ref needs a value}"; shift 2 ;;
        -c|--config)  CONFIG="${2:?--config needs a value}"; shift 2 ;;
        -s|--service) SERVICE="${2:?--service needs a value}"; shift 2 ;;
        -u|--url)     VERIFY_URL="${2:?--url needs a value}"; shift 2 ;;
        -C|--configure) CONFIGURE=1; shift ;;
        -n|--dry-run) DRY_RUN=1; shift ;;
        --sudo)       SUDO_MODE="always"; shift ;;
        --no-sudo)    SUDO_MODE="never"; shift ;;
        --no-restart) RESTART=0; shift ;;
        --clean)      CLEAN=1; shift ;;
        -h|--help)    usage; exit 0 ;;
        *)            die "unknown option: $1 (try --help)" ;;
    esac
done

command -v git >/dev/null || die "git is required to build the package"
git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1 || die "$REPO_DIR is not a git repository"
git -C "$REPO_DIR" rev-parse --verify --quiet "$REF" >/dev/null || die "no such git ref: $REF"

# ---------------------------------------------------------------------------
# Package. Deliberately built from the committed ref, not the working tree, so
# what lands on the station is something you can check out again later.
# ---------------------------------------------------------------------------
VERSION="$(sed -n 's/^ *version *= *"\(.*\)",\?$/\1/p' "$REPO_DIR/install.py" | head -1)"
VERSION="${VERSION:-unknown}"
COMMIT="$(git -C "$REPO_DIR" rev-parse --short "$REF")"
TARBALL_NAME="weewxha-${VERSION}.tar.gz"

step "Packaging weewxha $VERSION ($REF -> $COMMIT)"
if [ -n "$(git -C "$REPO_DIR" status --porcelain --untracked-files=no)" ]; then
    info "note: working tree has uncommitted changes; deploying $REF as committed"
fi

STAGING="$(mktemp -d)"
trap 'rm -rf "$STAGING"' EXIT
TARBALL="$STAGING/$TARBALL_NAME"
git -C "$REPO_DIR" archive --format=tar.gz --prefix=weewxha/ -o "$TARBALL" "$REF"
info "$TARBALL_NAME ($(du -h "$TARBALL" | cut -f1))"


# ---------------------------------------------------------------------------
# Interactive configuration. Everything is gathered up front so the deploy
# itself runs unattended, then applied to weewx.conf on the target.
# ---------------------------------------------------------------------------
CONFIG_JSON=""

ask() {   # ask <question> [default] -> answer on stdout
    local question="$1" default="${2:-}" answer
    if [ -n "$default" ]; then
        printf '  %s [%s]: ' "$question" "$default" > /dev/tty
    else
        printf '  %s: ' "$question" > /dev/tty
    fi
    IFS= read -r answer < /dev/tty || true
    printf '%s' "${answer:-$default}"
}

ask_secret() {   # never echoed, never shown back
    local question="$1" answer
    printf '  %s: ' "$question" > /dev/tty
    IFS= read -r -s answer < /dev/tty || true
    printf '\n' > /dev/tty
    printf '%s' "$answer"
}

ask_yn() {   # ask_yn <question> <y|n> -> exit status
    local question="$1" default="$2" answer
    while :; do
        answer="$(ask "$question (y/n)" "$default")"
        case "$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
        esac
        printf '  please answer y or n\n' > /dev/tty
    done
}

collect_config() {
    [ -e /dev/tty ] || die "--configure needs a terminal to ask questions on"

    step "Configuring weewxha"
    info "Enter accepts the default shown in brackets"

    printf '\n  \033[1mUnits\033[0m\n' > /dev/tty
    local units
    units="$(ask 'us, metric, metricwx, or keep (leave weewx.conf alone)' 'keep')"
    case "$units" in
        us|metric|metricwx|keep) ;;
        *) die "units must be one of: us, metric, metricwx, keep" ;;
    esac

    printf '\n  \033[1mZambretti forecast\033[0m\n' > /dev/tty
    local fc_enable="true" trend_period baro_lower baro_upper
    ask_yn 'Enable the forecast?' 'y' || fc_enable="false"
    trend_period="$(ask 'Pressure trend window, seconds' '10800')"
    baro_lower="$(ask 'Lowest pressure your station sees, hPa' '950.0')"
    baro_upper="$(ask 'Highest pressure your station sees, hPa' '1050.0')"

    printf '\n  \033[1mPressure source\033[0m\n' > /dev/tty
    info "answer no unless your station has no barometer of its own"
    local ha_enable="false" ha_url="" ha_entity="" ha_timeout="10" ha_unit=""
    local ha_token="" ha_verify="true" ha_ca_file=""
    if ask_yn 'Take the pressure from a Home Assistant sensor?' 'n'; then
        ha_enable="true"
        ha_url="$(ask 'Home Assistant URL' 'http://homeassistant.local:8123')"
        ha_entity="$(ask 'Pressure entity id' 'sensor.outdoor_pressure')"
        info "the entity must report SEA-LEVEL pressure, not absolute/station pressure"
        ha_timeout="$(ask 'Request timeout, seconds' '10')"
        ha_unit="$(ask "Unit, only if the entity has none (blank to read it from the entity)" '')"

        case "$ha_url" in
            https://*)
                printf '\n  TLS. A certificate from a private CA fails verification against\n' > /dev/tty
                printf '  the system trust store. Naming that CA keeps verification on;\n' > /dev/tty
                printf '  ignoring the check exposes the access token on the network.\n' > /dev/tty
                if ask_yn 'Verify the TLS certificate?' 'y'; then
                    ha_ca_file="$(ask 'CA certificate file (blank = system trust store)' '')"
                else
                    ha_verify="false"
                fi
                ;;
        esac

        printf '\n  Home Assistant: profile -> Security -> Long-lived access tokens\n' > /dev/tty
        ha_token="$(ask_secret 'Long-lived access token (not echoed)')"
        [ -n "$ha_token" ] || die "a token is required"
    fi

    # Summary, secrets shown only as whether they were given.
    printf '\n' > /dev/tty
    step "Settings to apply"
    info "units:            $units"
    info "forecast:         enable=$fc_enable trend_period=$trend_period baro=$baro_lower-$baro_upper"
    if [ "$ha_enable" = "true" ]; then
        info "pressure source:  $ha_url ($ha_entity)"
        info "authentication:   access token (${#ha_token} characters, stored mode 600)"
        case "$ha_url" in
            https://*)
                if [ "$ha_verify" = "false" ]; then
                    info "TLS:              NOT verified -- the token is exposed in transit"
                elif [ -n "$ha_ca_file" ]; then
                    info "TLS:              verified against $ha_ca_file"
                else
                    info "TLS:              verified against the system trust store"
                fi
                ;;
        esac
    else
        info "pressure source:  the station's own barometer"
    fi
    ask_yn 'Apply these?' 'y' || die "nothing applied"

    # Build the payload as JSON via python, so quotes and odd characters in a
    # token survive intact. Values go through the environment rather than
    # argv, which would be visible in ps.
    CONFIG_JSON="$STAGING/weewxha-config.json"
    ( umask 077
      CFG_UNITS="$units" \
      CFG_FC_ENABLE="$fc_enable" CFG_TREND="$trend_period" \
      CFG_BARO_LOWER="$baro_lower" CFG_BARO_UPPER="$baro_upper" \
      CFG_HA_ENABLE="$ha_enable" CFG_HA_URL="$ha_url" CFG_HA_ENTITY="$ha_entity" \
      CFG_HA_TIMEOUT="$ha_timeout" CFG_HA_UNIT="$ha_unit" \
      CFG_HA_TOKEN="$ha_token" \
      CFG_HA_VERIFY="$ha_verify" CFG_HA_CA_FILE="$ha_ca_file" \
      python3 -c '
import json, os
e = os.environ.get
units = e("CFG_UNITS")
groups = {
    "us": {"group_temperature": "degree_F", "group_pressure": "inHg",
           "group_speed": "mile_per_hour", "group_rain": "inch",
           "group_rainrate": "inch_per_hour", "group_altitude": "foot"},
    "metric": {"group_temperature": "degree_C", "group_pressure": "mbar",
               "group_speed": "km_per_hour", "group_rain": "cm",
               "group_rainrate": "cm_per_hour", "group_altitude": "meter"},
    "metricwx": {"group_temperature": "degree_C", "group_pressure": "hPa",
                 "group_speed": "meter_per_second", "group_rain": "mm",
                 "group_rainrate": "mm_per_hour", "group_altitude": "meter"},
}.get(units)

out = {
    "units": groups,
    "forecast": {
        "enable": e("CFG_FC_ENABLE"),
        "trend_period": e("CFG_TREND"),
        "baro_lower": e("CFG_BARO_LOWER"),
        "baro_upper": e("CFG_BARO_UPPER"),
    },
    "homeassistant": None,
    "secrets": {},
    "clear": [],
}

if e("CFG_HA_ENABLE") == "true":
    ha = {"enable": "true", "url": e("CFG_HA_URL"),
          "entity_id": e("CFG_HA_ENTITY"), "timeout": e("CFG_HA_TIMEOUT"),
          "verify": e("CFG_HA_VERIFY")}
    if e("CFG_HA_CA_FILE"):
        ha["ca_file"] = e("CFG_HA_CA_FILE")
    else:
        out["clear"].append("ca_file")
    if e("CFG_HA_UNIT"):
        ha["unit"] = e("CFG_HA_UNIT")
    else:
        out["clear"].append("unit")
    out["secrets"]["token"] = e("CFG_HA_TOKEN")
    # The inline form is cleared: the token is stored in a file instead.
    out["clear"].append("token")
    out["homeassistant"] = ha
else:
    out["homeassistant"] = {"enable": "false"}

print(json.dumps(out))
' > "$CONFIG_JSON" )
    chmod 600 "$CONFIG_JSON"
}

if [ "$CONFIGURE" = "1" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        step "Configuring weewxha"
        info "dry run: skipping the questions"
    else
        collect_config
    fi
fi

# ---------------------------------------------------------------------------
# The installer below runs on the WeeWX host, local or remote alike.
# ---------------------------------------------------------------------------
read -r -d '' INSTALLER <<'REMOTE_SCRIPT' || true
set -euo pipefail

TARBALL="$1"; SERVICE="$2"; CONFIG="$3"
DRY_RUN="$4"; RESTART="$5"; CLEAN="$6"; SUDO_MODE="$7"; SELF="${8:-}"
CONFIG_JSON="${9:-}"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

APPLIER=""
# Remove everything uploaded, however this exits. The answers file carries the
# access token, so leaving it behind on a failure would be worse than the
# failure itself.
cleanup() {
    [ -n "$APPLIER" ] && rm -f "$APPLIER"
    if [ "$DRY_RUN" != "1" ]; then
        rm -f "$TARBALL"
        [ -n "$CONFIG_JSON" ] && rm -f "$CONFIG_JSON"
        [ -n "$SELF" ] && rm -f "$SELF"
    fi
    return 0
}
trap cleanup EXIT


# WeeWX 5 ships weectl; WeeWX 4 ships wee_extension. They take different flags.
if command -v weectl >/dev/null 2>&1; then
    WEEWX_MAJOR=5
    CONFIG_ARG=""
    [ -n "$CONFIG" ] && CONFIG_ARG="--config=$CONFIG"
elif command -v wee_extension >/dev/null 2>&1; then
    WEEWX_MAJOR=4
    CONFIG_ARG=""
    [ -n "$CONFIG" ] && CONFIG_ARG="--config=$CONFIG"
else
    die "found neither weectl (WeeWX 5) nor wee_extension (WeeWX 4) on PATH"
fi
info "WeeWX $WEEWX_MAJOR.x toolchain"

# A WeeWX 5 pip install lives under the invoking user's home and needs no root;
# a packaged install under /etc needs it. Work out which this is rather than
# assuming, so the script suits both.
choose_sudo() {
    SUDO=""
    case "$SUDO_MODE" in
        never)  return ;;
        always) SUDO="sudo"; return ;;
    esac
    [ "$(id -u)" -eq 0 ] && return
    command -v sudo >/dev/null 2>&1 || return

    local probe="$CONFIG"
    if [ -z "$probe" ]; then
        for candidate in "$HOME/weewx-data/weewx.conf" /etc/weewx/weewx.conf \
                         /home/weewx/weewx.conf /opt/weewx/weewx.conf; do
            [ -f "$candidate" ] && { probe="$candidate"; break; }
        done
    fi
    # Writable config means this is a user-owned install; leave sudo out of it.
    if [ -n "$probe" ] && [ -w "$probe" ]; then
        return
    fi
    SUDO="sudo"
}
choose_sudo
[ -n "$SUDO" ] && info "using sudo (WeeWX looks root-owned here)"

run() {
    if [ "$DRY_RUN" = "1" ]; then
        info "would run: $*"
    else
        info "\$ $*"
        "$@"
    fi
}

if [ "$CLEAN" = "1" ]; then
    step "Removing the existing extension"
    info "resets skin/HTML_ROOT/enable to defaults; [[[Units]]] and [[[Forecast]]] survive"
    if [ "$WEEWX_MAJOR" = "5" ]; then
        run $SUDO weectl extension uninstall weewxha --yes ${CONFIG_ARG:+$CONFIG_ARG} || \
            info "nothing to uninstall"
    else
        run $SUDO wee_extension --uninstall=weewxha ${CONFIG_ARG:+$CONFIG_ARG} || \
            info "nothing to uninstall"
    fi
fi

step "Installing the extension"
if [ "$WEEWX_MAJOR" = "5" ]; then
    # weectl has its own --dry-run, which reports every file it would copy.
    if [ "$DRY_RUN" = "1" ]; then
        $SUDO weectl extension install "$TARBALL" --yes --dry-run --verbosity=2 ${CONFIG_ARG:+$CONFIG_ARG}
    else
        run $SUDO weectl extension install "$TARBALL" --yes ${CONFIG_ARG:+$CONFIG_ARG}
    fi
else
    run $SUDO wee_extension --install="$TARBALL" ${CONFIG_ARG:+$CONFIG_ARG}
fi

# weewxha 0.1.0 put the search list extension beside the templates, where
# Python could never import it. Installing doesn't remove files from older
# layouts, so clear that one out to avoid confusing future debugging.
#
# Paths come from the config we just installed against -- guessing at standard
# locations would quietly miss a non-default install.
step "Clearing files left by older versions"

CONFIG_PATH="$CONFIG"
if [ -z "$CONFIG_PATH" ]; then
    for candidate in "$HOME/weewx-data/weewx.conf" /etc/weewx/weewx.conf \
                     /home/weewx/weewx.conf /opt/weewx/weewx.conf; do
        [ -f "$candidate" ] && { CONFIG_PATH="$candidate"; break; }
    done
fi

if [ -n "$CONFIG_PATH" ] && [ -f "$CONFIG_PATH" ]; then
    # First value of a key, minus any inline comment and trailing space.
    cfg_value() {
        sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$CONFIG_PATH" \
            | sed -e 's/[[:space:]]*#.*$//' -e 's/[[:space:]]*$//' \
            | head -1
    }
    WEEWX_ROOT="$(cfg_value WEEWX_ROOT)"
    [ -n "$WEEWX_ROOT" ] || WEEWX_ROOT="$(dirname "$CONFIG_PATH")"
    SKIN_ROOT="$(cfg_value SKIN_ROOT)"
    [ -n "$SKIN_ROOT" ] || SKIN_ROOT="skins"
    case "$SKIN_ROOT" in
        /*) ;;
        *) SKIN_ROOT="$WEEWX_ROOT/$SKIN_ROOT" ;;
    esac

    stale="$SKIN_ROOT/weewxha/weewxha_search.py"
    if [ -f "$stale" ]; then
        info "found a 0.1.0 leftover"
        run $SUDO rm -f "$stale"
    else
        info "none found"
    fi
else
    info "could not locate weewx.conf; skipped (harmless -- any leftover is inert)"
fi


if [ -n "$CONFIG_JSON" ] && [ "$DRY_RUN" != "1" ]; then
    step "Writing settings into weewx.conf"

    # configobj is a hard dependency of WeeWX, but on a pip install it lives in
    # that install's environment rather than the system python. Prefer the
    # interpreter weectl runs under, then fall back -- and confirm the choice
    # can actually import configobj rather than assuming it.
    pick_python() {
        local candidates=() launcher shebang parts=()
        launcher="$(command -v weectl 2>/dev/null || command -v wee_extension 2>/dev/null || true)"
        if [ -n "$launcher" ]; then
            shebang="$(sed -n '1s/^#!//p' "$launcher" || true)"
            if [ -n "$shebang" ]; then
                read -r -a parts <<< "$shebang"
                # "#!/usr/bin/env python3" names the interpreter in argument 2.
                if [ "${#parts[@]}" -gt 0 ] && [ "$(basename "${parts[0]}")" = "env" ]; then
                    parts=("${parts[@]:1}")
                fi
                [ "${#parts[@]}" -gt 0 ] && candidates+=("${parts[0]}")
            fi
        fi
        candidates+=(python3 python)
        local candidate
        for candidate in "${candidates[@]}"; do
            if command -v "$candidate" >/dev/null 2>&1 \
               && "$candidate" -c "import configobj" >/dev/null 2>&1; then
                command -v "$candidate"
                return 0
            fi
        done
        return 1
    }
    PYTHON="$(pick_python)" || die "no python here can import configobj (WeeWX needs it)"
    info "using $PYTHON"

    APPLIER="/tmp/weewxha-apply-$$.py"
    cat > "$APPLIER" <<'PYAPPLY'
"""Merge the answers from deploy.sh --configure into weewx.conf."""
import json
import os
import sys

import configobj

answers_path, config_path = sys.argv[1], sys.argv[2]
weewx_user = sys.argv[3] if len(sys.argv) > 3 else ""

if not config_path:
    for candidate in (os.path.expanduser("~/weewx-data/weewx.conf"),
                      "/etc/weewx/weewx.conf", "/home/weewx/weewx.conf",
                      "/opt/weewx/weewx.conf"):
        if os.path.isfile(candidate):
            config_path = candidate
            break
if not config_path or not os.path.isfile(config_path):
    sys.exit("could not find weewx.conf; pass --config to deploy.sh")

with open(answers_path) as fh:
    answers = json.load(fh)

config = configobj.ConfigObj(config_path, encoding="utf-8", interpolation=False)
report = config.setdefault("StdReport", {}).setdefault("weewxha", {})


def write_secret(name, value):
    """Store a secret beside weewx.conf, readable only by the WeeWX user.

    weewx.conf is usually world-readable, so the secret goes in its own file
    at mode 600 and the config only points at it. Ownership has to follow the
    user weewxd runs as, NOT weewx.conf's owner: weewx.conf is typically
    root-owned and world-readable, so matching it would leave a mode-600 file
    that root alone can read and weewxd cannot.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(config_path)),
                        "weewxha_ha_%s" % name)
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w") as fh:
        fh.write(value)
    os.chmod(path, 0o600)

    owner = None
    if weewx_user:
        try:
            import pwd
            entry = pwd.getpwnam(weewx_user)
            os.chown(path, entry.pw_uid, entry.pw_gid)
            owner = weewx_user
        except (KeyError, OSError, ImportError):
            pass
    if owner is None:
        # No service user to go on. Fall back to weewx.conf's owner and say so,
        # since a mode-600 file the WeeWX user can't read fails at runtime.
        try:
            stat = os.stat(config_path)
            os.chown(path, stat.st_uid, stat.st_gid)
            import pwd
            owner = pwd.getpwuid(stat.st_uid).pw_name
        except (KeyError, OSError, ImportError, AttributeError):
            owner = "unchanged"
        print("    note: could not determine the user weewxd runs as; %s owns "
              "%s. If WeeWX logs a permission error, chown it to that user."
              % (owner, path))
    return path, owner


changed = []

if answers.get("units"):
    groups = report.setdefault("Units", {}).setdefault("Groups", {})
    groups.update(answers["units"])
    changed.append("units")

if answers.get("forecast"):
    forecast = report.setdefault("Forecast", {})
    forecast.update(answers["forecast"])
    changed.append("forecast")

ha_answers = answers.get("homeassistant")
if ha_answers is not None:
    ha = report.setdefault("Forecast", {}).setdefault("HomeAssistant", {})
    ha.update(ha_answers)

    for name, value in (answers.get("secrets") or {}).items():
        secret_path, owner = write_secret(name, value)
        ha["%s_file" % name] = secret_path
        print("    wrote %s (mode 600, owner %s)" % (secret_path, owner))

    # Drop the inline copies of anything now stored in a file, so a secret
    # can't linger in world-readable weewx.conf.
    for key in answers.get("clear") or []:
        if key in ha and "%s_file" % key not in answers.get("secrets", {}):
            del ha[key]
    changed.append("pressure source")

config.write()
print("    updated %s (%s)" % (config_path, ", ".join(changed) or "no changes"))
PYAPPLY

    # weewxd usually runs as its own unprivileged user; the token file has to
    # belong to that user, not to whoever owns weewx.conf.
    WEEWX_USER="$(systemctl show "$SERVICE" -p User --value 2>/dev/null || true)"
    if [ -z "$WEEWX_USER" ]; then
        WEEWX_USER="$(ps -o user= -C weewxd 2>/dev/null | head -1 | tr -d ' ' || true)"
    fi
    [ -n "$WEEWX_USER" ] && info "weewxd runs as $WEEWX_USER"

    run $SUDO "$PYTHON" "$APPLIER" "$CONFIG_JSON" "$CONFIG" "$WEEWX_USER"
fi

if [ "$RESTART" = "1" ]; then
    step "Restarting $SERVICE"
    if command -v systemctl >/dev/null 2>&1; then
        run $SUDO systemctl restart "$SERVICE"
        [ "$DRY_RUN" = "1" ] || sleep 2
        if [ "$DRY_RUN" != "1" ]; then
            if systemctl is-active --quiet "$SERVICE"; then
                info "$SERVICE is running"
            else
                die "$SERVICE did not come back up -- check: journalctl -u $SERVICE -n 50"
            fi
        fi
    else
        info "no systemctl here; restart WeeWX yourself"
    fi
else
    step "Skipping restart (--no-restart)"
    info "the new skin takes effect at the next report cycle"
fi

step "Verifying the install"
if [ "$WEEWX_MAJOR" = "5" ]; then
    if [ "$DRY_RUN" = "1" ]; then
        info "would run: weectl extension list"
    else
        $SUDO weectl extension list ${CONFIG_ARG:+$CONFIG_ARG} | sed 's/^/    /'
    fi
fi

# Uploaded files are removed by the EXIT trap, so there is no second SSH
# connection just to clean up.
exit 0
REMOTE_SCRIPT

if [ -n "$HOST" ]; then
    # Every scp/ssh below shares one multiplexed connection, so you authenticate
    # once for the whole deploy instead of once per command. The master socket
    # lives in the staging dir and is closed on exit.
    CONTROL_PATH="$STAGING/ssh-%C"
    SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=$CONTROL_PATH" -o ControlPersist=120)

    close_ssh() {
        ssh "${SSH_OPTS[@]}" -O exit "$HOST" 2>/dev/null || true
        rm -rf "$STAGING"
    }
    trap close_ssh EXIT

    step "Connecting to $HOST"
    # Open the shared connection up front, so any passphrase or password prompt
    # happens once, here, rather than partway through the deploy.
    if ! ssh "${SSH_OPTS[@]}" "$HOST" true; then
        die "could not connect to $HOST"
    fi
    info "connection established and shared for the rest of the run"

    REMOTE_TARBALL="/tmp/$TARBALL_NAME"
    REMOTE_SCRIPT_PATH="/tmp/weewxha-install-$$.sh"
    REMOTE_CONFIG_JSON=""
    [ -n "$CONFIG_JSON" ] && REMOTE_CONFIG_JSON="/tmp/weewxha-config-$$.json"

    # Ship the installer as a file rather than piping it into ssh's stdin.
    # Piping would leave sudo with nowhere to read a password from -- it needs
    # stdin to be the terminal, which is also why -t is used below.
    SCRIPT_FILE="$STAGING/weewxha-install.sh"
    printf '%s\n' "$INSTALLER" > "$SCRIPT_FILE"

    step "Copying to $HOST"
    if [ "$DRY_RUN" = "1" ]; then
        info "would copy: $TARBALL_NAME and the installer -> $HOST:/tmp/"
        # Still hand the payload a path so its dry-run output reads correctly.
    else
        # Both files in one scp, over the connection already open.
        scp "${SSH_OPTS[@]}" -q "$TARBALL" "$HOST:$REMOTE_TARBALL"
        scp "${SSH_OPTS[@]}" -q "$SCRIPT_FILE" "$HOST:$REMOTE_SCRIPT_PATH"
        if [ -n "$CONFIG_JSON" ]; then
            # Answers include secrets: create it mode 600 before writing.
            ssh "${SSH_OPTS[@]}" "$HOST" \
                "umask 077 && : > '$REMOTE_CONFIG_JSON'"
            scp "${SSH_OPTS[@]}" -q "$CONFIG_JSON" "$HOST:$REMOTE_CONFIG_JSON"
        fi
        info "$HOST:$REMOTE_TARBALL"
    fi

    # Allocate a TTY when we have one, so sudo can prompt. Without a terminal
    # on this side, skip -t and let sudo fail loudly rather than hang.
    TTY_FLAG=()
    [ -t 0 ] && TTY_FLAG=(-t)

    # The payload removes both uploaded files itself, so there's no extra
    # connection just to clean up.
    ssh "${SSH_OPTS[@]}" "${TTY_FLAG[@]}" "$HOST" \
        "bash '$REMOTE_SCRIPT_PATH' '$REMOTE_TARBALL' '$SERVICE' '$CONFIG' '$DRY_RUN' '$RESTART' '$CLEAN' '$SUDO_MODE' '$REMOTE_SCRIPT_PATH' '$REMOTE_CONFIG_JSON'"
else
    bash -s -- "$TARBALL" "$SERVICE" "$CONFIG" "$DRY_RUN" "$RESTART" "$CLEAN" \
        "$SUDO_MODE" "" "$CONFIG_JSON" <<< "$INSTALLER"
fi

# ---------------------------------------------------------------------------
# Optional end-to-end check against the published feed.
# ---------------------------------------------------------------------------
if [ -n "$VERIFY_URL" ] && [ "$DRY_RUN" != "1" ]; then
    step "Checking the published feed"
    info "$VERIFY_URL"
    # Reports regenerate once per archive interval, so the feed may still be
    # the pre-deploy one for a few minutes.
    if ! curl -fsS "$VERIFY_URL" -o "$STAGING/feed.json"; then
        die "could not fetch $VERIFY_URL"
    fi
    python3 - "$STAGING/feed.json" <<'PY'
import json, sys
with open(sys.argv[1]) as fh:
    data = json.load(fh)
forecast = data.get("forecast") or {}
zam = (forecast.get("zambretti") or {}).get("value")
trend = (forecast.get("pressure_trend") or {}).get("value")
print("    generated_at:", data.get("generated_at"))
print("    forecast    :", zam if zam else "(none yet)")
print("    trend       :", trend if trend else "(needs a full trend window of history)")
if "forecast" not in data:
    sys.exit("    feed has no forecast section -- is the running skin the new one?")
PY
fi

step "Done"
if [ "$DRY_RUN" = "1" ]; then
    info "dry run: nothing was changed"
else
    info "deployed weewxha $VERSION ($COMMIT)${HOST:+ to $HOST}"
fi

#BEGIN PREPARE_CONFFILE_TRANSFER
prepare_conffile_transfer() {
    local conffile="$1"
    local lastver="$2"
    local pkgfrom="$3"
    local pkgto="$4"

    if [ "$5" != "--" ]; then
        echo "prepare_conffile_transfer called with the wrong number of arguments" >&2
        return 1
    fi
    for _ in $(seq 1 5); do
        shift
    done

    # If we're installing from scratch or upgrading from a new enough version
    # of the package, then no transfer needs to happen and we can stop here
    if [ -z "$2" ] || dpkg --compare-versions -- "$2" gt "$lastver"; then
        return 0
    fi

    # Depending on the current state of the conffile, we need to perform different
    # steps to transfer it. Moving the conffile to a different location depending
    # on its current state achieves two goals: dpkg will see the conffile is no
    # longer present on disk after $pkgfrom has been upgraded, and so it will no
    # longer associate it with that package (not even as an obsolete conffile);
    # more importanly, $pkgto's postinst, where the transfer process is completed,
    # will be able to figure out the original state of the conffile and make sure
    # it is restored
    if [ -e "$conffile" ]; then
        echo "Preparing transfer of config file $conffile (from $pkgfrom to $pkgto) ..."
        mv -f "$conffile" "$conffile.dpkg-transfer"
    else
        # If the conffile is no longer present on the disk, it means the admin
        # has deleted it, and we should preserve this local modification
        touch "$conffile.dpkg-disappear"
    fi
}
#END PREPARE_CONFFILE_TRANSFER

#BEGIN FINISH_CONFFILE_TRANSFER
finish_conffile_transfer() {
    local conffile="$1"
    local lastver="$2"
    local pkgfrom="$3"
    local pkgto="$4"

    if [ "$5" != "--" ]; then
        echo "finish_conffile_transfer called with the wrong number of arguments" >&2
        return 1
    fi
    for _ in $(seq 1 5); do
        shift
    done

    # If we're upgrading rather than installing from scratch, we can assume
    # the transfer must have happened at some point in the past and stop here
    if [ -n "$2" ]; then
        return 0
    fi

    if [ -e "$conffile.dpkg-transfer" ]; then
        # Complete the process started in $pkgfrom's preinst by restoring the
        # version of the conffile containing local modifications
        echo "Finishing transfer of config file $conffile (from $pkgfrom to $pkgto) ..."
        mv -f "$conffile.dpkg-transfer" "$conffile"
        return 0
    fi

    if [ -e "$conffile.dpkg-disappear" ]; then
        # The conffile had been deleted by the admin, so let's return to
        # that state
        rm -f "$conffile" "$conffile.dpkg-disappear"
        return 0
    fi
}
#END FINISH_CONFFILE_TRANSFER

#BEGIN ABORT_CONFFILE_TRANSFER
abort_conffile_transfer() {
    local conffile="$1"
    local lastver="$2"
    local pkgfrom="$3"
    local pkgto="$4"

    if [ "$5" != "--" ]; then
        echo "abort_conffile_transfer called with the wrong number of arguments" >&2
        return 1
    fi
    for _ in $(seq 1 5); do
        shift
    done

    # If we were installing from scratch or upgrading from a new enough version
    # when the error occurred, then no transfer was in progress and we don't
    # need to rollback any changes
    if [ -z "$2" ] || dpkg --compare-versions -- "$2" gt "$lastver"; then
        return 0
    fi

    # If the conffile was being transferred, return it to its original location
    if [ -e "$conffile.dpkg-transfer" ]; then
        mv -f "$conffile.dpkg-transfer" "$conffile"
    fi

    # Clean up additional state
    rm -f "$conffile.dpkg-disappear"
}
#END ABORT_CONFFILE_TRANSFER

#BEGIN CREATE_CONFIG_FROM_TEMPLATE
create_config_from_template() {
    local config="$1"
    local template="$2"
    local lastver="$3"

    if [ "$4" != "--" ]; then
        echo "create_config_from_template called with the wrong number of arguments" >&2
        return 1
    fi
    for _ in $(seq 1 4); do
        shift
    done

    if [ -n "$2" ] && dpkg --compare-versions -- "$2" gt "$lastver"; then
        # The package is already configured, and the version that's been
        # configured is new enough to contain the config file
        if [ -e "$config.dpkg-backup" ]; then
            # The package had been configured in the past and has
            # subsequently been removed without purging, so a backup of
            # the config file is still present on the disk. Restore it
            mv -f "$config.dpkg-backup" "$config"
            return 0
        else
            # We're doing a regular upgrade. Don't change anything
            return 0
        fi
    else
        # We're either installing from scratch, or upgrading from a version
        # that didn't have the config file yet. Make a copy of the template
        # in the appropriate location and with the expected permissions
        install -o root -g root -m 0600 "$template" "$config"
        return 0
    fi
}
#END CREATE_CONFIG_FROM_TEMPLATE

#BEGIN REMOVE_CONFIG_FROM_TEMPLATE
remove_config_from_template() {
    local config="$1"
    local template="$2"
    local lastver="$3"

    if [ "$4" != "--" ]; then
        echo "remove_config_from_template called with the wrong number of arguments" >&2
        return 1
    fi
    for _ in $(seq 1 4); do
        shift
    done

    if [ "$1" = "remove" ] && [ -e "$config" ]; then
        # When removing the package, move the configuration file to the side
        # so that the daemon no longer sees it, but we can still restore it
        # at a later time if the package is reinstalled
        mv -f "$config" "$config.dpkg-backup"
        return 0
    fi

    if [ "$1" = "purge" ]; then
        # When purging the package, remove all traces of the configuration
        rm -f "$config" "$config.dpkg-backup"
        return 0
    fi
}
#END REMOVE_CONFIG_FROM_TEMPLATE

#BEGIN SYSTEMD_DAEMON_RELOAD
systemd_daemon_reload() {
    if [ -z "${DPKG_ROOT:-}" ] && [ -d /run/systemd/system ]; then
        systemctl --system daemon-reload >/dev/null || true
    fi
}
#END SYSTEMD_DAEMON_RELOAD

#BEGIN SYSTEMD_UNIT_RESTART_IF_ACTIVE
systemd_unit_restart_if_active() {
    if [ -z "${DPKG_ROOT:-}" ] && [ -d /run/systemd/system ]; then
        for unit in "$@"; do
            if systemctl is-active -q "$unit"; then
                deb-systemd-invoke restart "$unit" >/dev/null || true
            fi
        done
    fi
}
#END SYSTEMD_UNIT_RESTART_IF_ACTIVE

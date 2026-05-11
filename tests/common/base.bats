setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
}

setup() {
    load common
}

@test "gcsfuse" {
    run_in_container gcsfuse -v
}

@test "wb cli" {
    run_in_container wb version
}

@test "fuse.conf user_allow_other" {
    run_in_container 'grep -qE "^[[:space:]]*[^#]*user_allow_other" "/etc/fuse.conf"'
}

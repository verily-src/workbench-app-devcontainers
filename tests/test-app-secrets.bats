setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
}

setup() {
    load common/common
}

get_pid1_env() {
    exec_in_container root \
        sh -c "tr '\0' '\n' < /proc/1/environ | grep \"^${1}=\" | sed \"s/^${1}=//\""
}

@test "secret pipe is removed after injection" {
    ! exec_in_container root test -e /tmp/secrets
}

@test "secret: EXAMPLE_SECRET has correct value" {
    result="$(get_pid1_env EXAMPLE_SECRET)"
    [ "$result" = "test-value-secret" ]
}

@test "secret: PIPE_SECRET fd can only be read once" {
    fd_path="$(get_pid1_env PIPE_SECRET)"
    fd="${fd_path#/dev/fd/}"
    result="$(exec_in_container root cat "/proc/1/fd/${fd}")"
    [ "$result" = "test-pipe-secret" ]
    result="$(exec_in_container root cat "/proc/1/fd/${fd}")"
    [ "$result" = "" ]
}

@test "secret: PATH_SECRET fd is readable multiple times" {
    fd_path="$(get_pid1_env PATH_SECRET)"
    fd="${fd_path#/dev/fd/}"
    result="$(exec_in_container root cat "/proc/1/fd/${fd}")"
    [ "$result" = "test-path-secret" ]
    result="$(exec_in_container root cat "/proc/1/fd/${fd}")"
    [ "$result" = "test-path-secret" ]
}

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

@test "secret: SECRET_VALUE has correct value" {
    result="$(get_pid1_env SECRET_VALUE)"
    [ "$result" = "secret-value" ]
}

@test "secret: SECRET_PIPE fd can only be read once" {
    fd_path="$(get_pid1_env SECRET_PIPE)"
    fd="${fd_path#/dev/fd/}"
    result="$(exec_in_container root cat "/proc/1/fd/${fd}")"
    [ "$result" = "secret-value" ]
    result="$(exec_in_container root cat "/proc/1/fd/${fd}")"
    [ "$result" = "" ]
}

@test "secret: SECRET_PATH fd is readable multiple times" {
    fd_path="$(get_pid1_env SECRET_PATH)"
    fd="${fd_path#/dev/fd/}"
    result="$(exec_in_container root cat "/proc/1/fd/${fd}")"
    [ "$result" = "secret-value" ]
    result="$(exec_in_container root cat "/proc/1/fd/${fd}")"
    [ "$result" = "secret-value" ]
}

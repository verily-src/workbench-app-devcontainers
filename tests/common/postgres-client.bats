setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
}

setup() {
    load common
}

@test "psql" {
    run_in_container psql --version
}

@test "pg_dump" {
    run_in_container pg_dump --version
}

@test "pg_restore" {
    run_in_container pg_restore --version
}

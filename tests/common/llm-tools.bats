setup_file() {
    echo "# Running ${BATS_TEST_FILENAME##*/}" >&3
}

setup() {
    load common
}

@test "node" {
    run_in_container node --version
}

@test "npm" {
    run_in_container npm --version
}

@test "claude" {
    run_in_container claude --version
}

@test "gemini" {
    run_in_container gemini --version
}

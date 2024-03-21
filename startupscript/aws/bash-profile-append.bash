
# Prompt user to authenticate with Workbench CLI if they are not already
# authenticated. Note the lack of a shebang is intentional.  This file will be
# appended to the user's .bash_profile file, and is kept separate so that this 
# code can be linted with shellcheck.

if [[ "$("${WORKBENCH_INSTALL_PATH}" auth status --format json | jq .loggedIn)" == false ]]; then
    echo "User must log into Workbench to continue."
    "${WORKBENCH_INSTALL_PATH}" auth login
    configure_workbench
fi

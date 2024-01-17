#!/bin/bash

# bash-completion.sh
#
# Writes a block to the user's ~/.bashrc file such that Bash shells pick up
# any Bash completion scripts that have been installed.
#
# Note that this script is intended to be source from the "post-startup.sh" script
# and is dependent on some functions and variables already being set up:
#
# - emit (function)
# - USER_BASHRC: path to user's ~/.bashrc file

emit "Configuring bash completion for the VM..."

cat << 'EOF' >> "${USER_BASHRC}"

# Source available global bash tab completion scripts
if [[ -d /etc/bash_completion.d ]]; then
 for BASH_COMPLETION_SCRIPT in /etc/bash_completion.d/* ; do
   source "${BASH_COMPLETION_SCRIPT}"
 done
fi

# Source available user installed bash tab completion scripts
if [[ -d ~/.bash_completion.d ]]; then
 for BASH_COMPLETION_SCRIPT in ~/.bash_completion.d/* ; do
   source "${BASH_COMPLETION_SCRIPT}"
 done
fi
EOF

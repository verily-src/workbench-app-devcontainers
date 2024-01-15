#!/bin/bash
emit "Installing Java JDK ..."

# Create a soft link in /usr/bin to the java runtime
ln -sf "$(which java)" "/usr/bin"
chown --no-dereference "${user}" "/usr/bin/java"


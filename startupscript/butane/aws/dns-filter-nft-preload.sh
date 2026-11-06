#!/bin/bash
# dns-filter-nft-preload.sh installs the DNS-filter bypass-block rule before Docker starts, for an
# instance already confirmed airlocked on a previous boot (see dns-filter-nft-preload.service's
# ConditionPathExists). Docker restarts already-existing restart-policy containers
# (application-server, proxy-agent) as part of its own startup, before dns-filter-setup.sh - which
# runs After=docker.service - gets a chance to apply the same rule via the DOCKER-USER chain. A
# standalone table is used here, not DOCKER-USER, since that chain doesn't exist until Docker
# creates it - this script runs before Docker has started at all this boot.
#
# This only covers reboots of an already-airlocked instance. On the genuine first boot this script
# doesn't run (the flag file doesn't exist yet); dns-filter-setup.sh still installs the equivalent
# rule there once it confirms the instance is airlocked, which is fine, since nothing has ever run
# on the instance yet to race against.

set -o errexit
set -o nounset
set -o pipefail
set -o xtrace

nft add table inet dns-filter-guard
nft add chain inet dns-filter-guard block_direct_dns "{ type filter hook forward priority -1 ; }"
nft add rule inet dns-filter-guard block_direct_dns iifname "br-*" ip daddr != 172.17.0.1 udp dport 53 drop
nft add rule inet dns-filter-guard block_direct_dns iifname "br-*" ip daddr != 172.17.0.1 tcp dport 53 drop

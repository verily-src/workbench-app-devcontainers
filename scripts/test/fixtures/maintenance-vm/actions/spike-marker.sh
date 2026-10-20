#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail

readonly spike="${WORKBENCH_MAINTENANCE_STATE_DIR:?}/spike"
case "${WORKBENCH_MAINTENANCE_ACTION_ID:?}" in
    spike-once) marker=once; dependency='' ;;
    spike-skipped) marker=skipped; dependency=once ;;
    spike-third) marker=third; dependency=skipped ;;
    spike-independent) marker=independent; dependency=third ;;
    spike-recovery) marker=recovery; dependency=third ;;
    spike-dependent) marker=dependent; dependency=recovery ;;
    *) exit 1 ;;
esac

if [[ -n "${dependency}" ]]; then
    [[ -f "${spike}/${dependency}" && "$(cat "${spike}/${dependency}")" == 1 ]]
fi
mkdir -p "${spike}"
if [[ -e "${spike}/${marker}" ]]; then
    [[ -f "${spike}/${marker}" && "$(cat "${spike}/${marker}")" == 1 ]]
    exit 0
fi

tmp="$(mktemp "${spike}/.${marker}.XXXXXX")"
trap 'rm -f -- "${tmp}"' EXIT
printf '1\n' > "${tmp}"
mv -f -- "${tmp}" "${spike}/${marker}"

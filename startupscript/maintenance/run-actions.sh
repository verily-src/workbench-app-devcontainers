#!/bin/bash

set -o errexit
set -o nounset
set -o pipefail

if [[ $# != 2 ]]; then
  echo 'Usage: run-actions.sh MANIFEST STATE_DIR' >&2
  exit 1
fi

readonly MANIFEST_PATH="$1"
readonly STATE_DIR="$2"
umask 077
[[ ! -L "$STATE_DIR" ]] || { echo 'State directory cannot be a symlink' >&2; exit 1; }
mkdir -p "$STATE_DIR"
chmod 0700 "$STATE_DIR"
[[ ! -L "$STATE_DIR/.lock" && ! -L "$STATE_DIR/state.json" ]] || exit 1
exec 9>"$STATE_DIR/.lock"
flock --nonblock 9 || { echo 'Maintenance is already running' >&2; exit 1; }

manifest_dir="$(realpath -- "$(dirname -- "$MANIFEST_PATH")")"
manifest="$(jq -ces '
  def id: type == "string" and test("^[A-Za-z0-9_-]{1,64}$");
  def ids: type == "array" and all(.[]; id) and length == (unique | length);
  if length != 1 then error("expected one manifest") else .[0] end |
  if type != "object" or .schema != 1 or (.actions | type) != "array" then
    error("invalid manifest schema")
  else . end |
  if all(.actions[];
    type == "object" and (.id | id) and
    (.script | type == "string" and test("^([A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\\.sh$")) and
    (.depends_on | ids) and (.replaces | ids) and (.required | type == "boolean") and
    ((keys - ["id", "script", "depends_on", "required", "replaces"]) | length == 0)
  ) | not then error("invalid action") else . end |
  [.actions[].id] as $ids |
  if ($ids | length) != ($ids | unique | length) then error("duplicate action ID") else . end |
  if all(.actions[]; all((.depends_on + .replaces)[]; . as $id | $ids | index($id))) | not
  then error("unknown action reference") else . end
' "$MANIFEST_PATH")"

if [[ -f "$STATE_DIR/state.json" ]]; then
  state="$(jq -ces '
    def id: type == "string" and test("^[A-Za-z0-9_-]{1,64}$");
    if length != 1 then error("expected one ledger") else .[0] end |
    if type != "object" or .schema != 1 or (.actions | type) != "object" then
      error("invalid ledger schema")
    else . end |
    if all(.actions | to_entries[];
      (.key | id) and (.value | type == "object" and
        (.sha256 | type == "string" and test("^[a-f0-9]{64}$")) and
        (.status == "succeeded" or .status == "failed" or .status == "replaced") and
        (.attempts | type == "number" and . >= 0 and floor == .) and
        ((has("last_error") | not) or (.last_error | type == "string" and length <= 256)) and
        (if .status == "replaced" then (.replaced_by | id) else true end))
    ) | not then error("invalid ledger action") else . end |
    . as $state |
    def satisfied($id; $seen):
      if $seen | index($id) then false
      elif $state.actions[$id].status == "succeeded" then true
      elif $state.actions[$id].status == "replaced" then
        satisfied($state.actions[$id].replaced_by; $seen + [$id])
      else false end;
    if all(.actions | to_entries[] | select(.value.status == "replaced"); satisfied(.key; []))
    then . else error("invalid replacement ledger") end
  ' "$STATE_DIR/state.json")"
else
  [[ ! -e "$STATE_DIR/state.json" ]] || exit 1
  state='{"schema":1,"actions":{}}'
fi

declare -A scripts
while IFS=$'\t' read -r id script; do
  resolved="$(realpath -- "$manifest_dir/$script")"
  [[ "$resolved" == "$manifest_dir/"* && -f "$resolved" ]] || {
    echo "Action $id leaves the manifest directory" >&2
    exit 1
  }
  digest="$(sha256sum -- "$resolved")"
  digest="${digest%% *}"
  previous="$(jq -r --arg id "$id" '.actions[$id].sha256 // empty' <<< "$state")"
  [[ -z "$previous" || "$previous" == "$digest" ]] || {
    echo "Action $id changed after being recorded" >&2
    exit 1
  }
  scripts["$id"]="$resolved"
  manifest="$(jq -c --arg id "$id" --arg digest "$digest" \
    '(.actions[] | select(.id == $id)).sha256 = $digest' <<< "$manifest")"
done < <(jq -r '.actions[] | [.id, .script] | @tsv' <<< "$manifest")

plan="$(jq -c '
  def resolve($id; $replacements; $seen):
    if $seen | index($id) then error("replacement cycle")
    elif $replacements[$id] then resolve($replacements[$id]; $replacements; $seen + [$id])
    else $id end;
  (reduce .actions[] as $action ({};
    reduce $action.replaces[] as $old (.;
      if has($old) then error("multiple replacements for one action")
      else .[$old] = $action.id end))) as $replacements |
  . as $manifest |
  [.actions[] | . + {
    effective_id: resolve(.id; $replacements; []),
    effective_deps: [.depends_on[] | resolve(.; $replacements; [])] | unique
  }] as $actions |
  {remaining: [$actions[] | select(.id == .effective_id)], order: []} |
  until(.remaining | length == 0;
    .order as $done |
    ([.remaining[] | select(all(.effective_deps[]; . as $dep | $done | index($dep)))] | sort_by(.id)) as $ready |
    if $ready | length == 0 then error("dependency cycle") else
      .order += [$ready[].id] | .remaining -= $ready
    end
  ) |
  .order as $order |
  $manifest + {order: $order, replaced: (reduce $order[] as $id ({};
    .[$id] = [$actions[] | select(.effective_id == $id and .id != $id) | .id]))}
' <<< "$manifest")"

state_tmp=''
trap '[[ -z "$state_tmp" ]] || rm -f -- "$state_tmp"' EXIT
commit_state() {
  state_tmp="$(mktemp "$STATE_DIR/.state.XXXXXX")"
  printf '%s\n' "$state" > "$state_tmp"
  mv -f -- "$state_tmp" "$STATE_DIR/state.json"
  state_tmp=''
}

while IFS= read -r id; do
  status="$(jq -r --arg id "$id" '.actions[$id].status // empty' <<< "$state")"
  [[ "$status" != succeeded && "$status" != replaced ]] || continue
  if ! jq -e --arg id "$id" --argjson state "$state" '
    all(.actions[] | select(.id == $id) | .depends_on[];
      $state.actions[.].status == "succeeded" or $state.actions[.].status == "replaced")
  ' <<< "$plan" >/dev/null; then
    echo "Maintenance action $id blocked by a failed dependency"
    continue
  fi
  digest="$(jq -r --arg id "$id" '.actions[] | select(.id == $id) | .sha256' <<< "$plan")"
  state="$(jq -c --arg id "$id" --arg digest "$digest" '
    .actions[$id] = {sha256: $digest, status: "failed",
      attempts: ((.actions[$id].attempts // 0) + 1), last_error: "interrupted"}
  ' <<< "$state")"
  commit_state
  echo "Running maintenance action $id"
  if WORKBENCH_MAINTENANCE_STATE_DIR="$STATE_DIR" WORKBENCH_MAINTENANCE_ACTION_ID="$id" \
      /bin/bash "${scripts[$id]}" 9>&-; then
    state="$(jq -c --arg id "$id" --argjson plan "$plan" '
      .actions[$id].status = "succeeded" | del(.actions[$id].last_error) |
      reduce $plan.replaced[$id][] as $old (.;
        .actions[$old] = {sha256: ($plan.actions[] | select(.id == $old) | .sha256),
          status: "replaced", attempts: (.actions[$old].attempts // 0), replaced_by: $id})
    ' <<< "$state")"
  else
    exit_status=$?
    state="$(jq -c --arg id "$id" --arg error "exit status $exit_status" \
      '.actions[$id].last_error = $error' <<< "$state")"
    echo "Maintenance action $id failed with exit status $exit_status" >&2
  fi
  commit_state
done < <(jq -r '.order[]' <<< "$plan")

jq -e --argjson state "$state" '
  all(.actions[] | select(.required); .id as $id |
    $state.actions[$id].status == "succeeded" or $state.actions[$id].status == "replaced")
' <<< "$plan" >/dev/null || { echo 'Required maintenance is incomplete' >&2; exit 1; }

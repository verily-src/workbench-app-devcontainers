# Temporary VM scenarios

1. These public fixtures add marker actions to the real host payload; they do not replace the production action runner, migration action, or app files.
2. `v1` runs `spike-once`; `v2` adds `spike-skipped`; `v3` adds `spike-third` after the skipped action.
3. `failure` adds an exit-42 required action, its required dependent, and an independent optional action; `recovery` replaces the failure and then runs its dependent.
4. `rollback` restores the v3 declarations; publish it under a higher numeric version, because removing an index entry does not downgrade an installed image.
5. Every successful marker contains one line, `1`, under `/var/lib/workbench-maintenance/spike`; pair it with `state.json` attempts to prove an action did not rerun.
6. `link-host-files.sha256` pins the canonical migration script; its source remains `startupscript/maintenance/actions/link-host-files.sh` and must not change between scenario builds.

Run the fixture tests after integration:

```sh
bats scripts/test/fixtures/maintenance-vm/scenarios.bats
```

In an isolated temporary source branch, select one scenario and overlay only its public fixture files before committing the source for an image build:

```sh
SCENARIO=v1
case "$SCENARIO" in v1|v2|v3|failure|recovery|rollback) ;; *) exit 1 ;; esac
FIXTURES=scripts/test/fixtures/maintenance-vm
(cd startupscript/maintenance && sha256sum --check "../../$FIXTURES/link-host-files.sha256")
cp "$FIXTURES/actions/"*.sh startupscript/maintenance/actions/
cp "$FIXTURES/$SCENARIO.json" startupscript/maintenance/actions.json
```

1. Keep the fixture action scripts byte-identical across every source commit; select scenarios by replacing only `actions.json`.
2. Build each selected source commit with the ordinary maintenance image entrypoint and a distinct increasing version; the source must be public before publication.
3. Test with v1 installed, skip v2 approval on that VM, then approve v3 and reboot; later use failure, recovery, and rollback versions.
4. These sources do not prove VM boot ordering, remote status, or container reuse; record those from the real VM separately.

#!/usr/bin/env bats

setup() {
    TOOL="${BATS_TEST_DIRNAME}/../../startupscript/butane/dependency-lock.mjs"
    ROOT="${BATS_TEST_TMPDIR}/repo"
    mkdir -p "${ROOT}/src/example" "${ROOT}/startupscript/butane" "${BATS_TEST_TMPDIR}/host"
    git init -q "${ROOT}"
    printf 'FROM example/base@sha256:%064d\nRUN echo original-code\n' 1 > "${ROOT}/src/example/Dockerfile"
    printf 'readonly IMAGE=example/tool@sha256:%064d\n' 2 > "${ROOT}/startupscript/butane/050-parse-devcontainer.sh"
    cp "${ROOT}/startupscript/butane/050-parse-devcontainer.sh" "${BATS_TEST_TMPDIR}/host/parse-devcontainer.sh"
    printf 'NODE_VERSION="v24.20.0"\nNODE_SHA256="%064d"\n' 3 > "${ROOT}/startupscript/butane/010-install-node.sh"
    printf '{"dependencies":{"@devcontainers/cli":"^0.64.0","jsonc-parser":"^3.2.1"}}\n' > "${ROOT}/startupscript/butane/package.json"
    cat > "${ROOT}/startupscript/butane/package-lock.json" <<'JSON'
{"lockfileVersion":3,"packages":{"":{"dependencies":{"@devcontainers/cli":"^0.64.0","jsonc-parser":"^3.2.1"}},"node_modules/@devcontainers/cli":{"version":"0.64.0","integrity":"sha512-AAAA","resolved":"https://registry.npmjs.org/@devcontainers/cli/-/cli-0.64.0.tgz"},"node_modules/jsonc-parser":{"version":"3.2.1","integrity":"sha512-AAAA","resolved":"https://registry.npmjs.org/jsonc-parser/-/jsonc-parser-3.2.1.tgz"}}}
JSON
    node -e '
      const fs=require("fs"); const artifact={url:"https://example.com/host.raw",sha256:"0".repeat(64)};
      fs.writeFileSync(process.argv[1],JSON.stringify({host_versions:{flatcar:"4593.2.5",compose:"2.39.3",buildx:"0.28.0",nvidia_driver:"580.178.04",nvidia_runtime:"1.17.8"},host_artifacts:{compose:artifact,buildx:artifact,nvidia_runtime:artifact}}));
    ' "${BATS_TEST_TMPDIR}/host.json"
    git -C "${ROOT}" add .
    node "${TOOL}" export "${ROOT}" "${BATS_TEST_TMPDIR}/host.json" "${BATS_TEST_TMPDIR}/lock.json"
}

@test "native CLI and host Node are locked without container package replay" {
    run node -e '
      const lock=require(process.argv[1]);
      if(lock.host_versions.devcontainer_cli!=="0.64.0" || lock.host_versions.node!=="24.20.0" || lock.digests.length!==2 || !lock.unpinned_risks.length)process.exit(1);
      if(JSON.stringify(lock).includes("original-code"))process.exit(1);
    ' "${BATS_TEST_TMPDIR}/lock.json"
    [ "${status}" -eq 0 ]
}

@test "new source code uses selected digests in app and installed host script" {
    sed 's/original-code/hotfix-code/; s/0000000001$/0000000009/' "${ROOT}/src/example/Dockerfile" > "${BATS_TEST_TMPDIR}/changed"
    mv "${BATS_TEST_TMPDIR}/changed" "${ROOT}/src/example/Dockerfile"
    sed 's/0000000002$/0000000008/' "${ROOT}/startupscript/butane/050-parse-devcontainer.sh" > "${BATS_TEST_TMPDIR}/host/parse-devcontainer.sh"
    cp "${BATS_TEST_TMPDIR}/host/parse-devcontainer.sh" "${ROOT}/startupscript/butane/050-parse-devcontainer.sh"
    run node "${TOOL}" apply "${ROOT}" "${BATS_TEST_TMPDIR}/lock.json" "${BATS_TEST_TMPDIR}/host"
    [ "${status}" -eq 0 ]
    grep -q 'hotfix-code' "${ROOT}/src/example/Dockerfile"
    grep -q '0000000001$' "${ROOT}/src/example/Dockerfile"
    grep -q '0000000002$' "${BATS_TEST_TMPDIR}/host/parse-devcontainer.sh"
}

@test "new covered pin fails before existing source files are changed" {
    printf 'FROM example/new@sha256:%064d\n' 4 >> "${ROOT}/src/example/Dockerfile"
    cp "${ROOT}/src/example/Dockerfile" "${BATS_TEST_TMPDIR}/before"
    run node "${TOOL}" apply "${ROOT}" "${BATS_TEST_TMPDIR}/lock.json"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *'source digest contract changed'* ]]
    cmp "${ROOT}/src/example/Dockerfile" "${BATS_TEST_TMPDIR}/before"
}

@test "removing a pin or replacing it with a floating tag fails" {
    printf 'FROM example/base:latest\n' > "${ROOT}/src/example/Dockerfile"
    run node "${TOOL}" apply "${ROOT}" "${BATS_TEST_TMPDIR}/lock.json"
    [ "${status}" -ne 0 ]
}

@test "conflicting native selectors fail export" {
    printf 'FROM example/base@sha256:%064d\n' 2 >> "${ROOT}/src/example/Dockerfile"
    run node "${TOOL}" export "${ROOT}" "${BATS_TEST_TMPDIR}/host.json" "${BATS_TEST_TMPDIR}/second.json"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *'conflicting digest selector'* ]]
}

@test "a symlink cannot write outside the selected source" {
    cp "${ROOT}/src/example/Dockerfile" "${BATS_TEST_TMPDIR}/outside"
    rm "${ROOT}/src/example/Dockerfile"
    ln -s "${BATS_TEST_TMPDIR}/outside" "${ROOT}/src/example/Dockerfile"
    run node "${TOOL}" apply "${ROOT}" "${BATS_TEST_TMPDIR}/lock.json"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *'not a regular file'* ]]
}

@test "mismatched CLI version and missing integrity are rejected" {
    node -e 'const fs=require("fs"),p=process.argv[1],x=JSON.parse(fs.readFileSync(p));x.host_versions.devcontainer_cli="0.89.0";fs.writeFileSync(p,JSON.stringify(x))' "${BATS_TEST_TMPDIR}/lock.json"
    run node "${TOOL}" validate "${BATS_TEST_TMPDIR}/lock.json"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *'CLI native lock disagrees'* ]]
    node -e 'const fs=require("fs"),p=process.argv[1],x=JSON.parse(fs.readFileSync(p));x.host_versions.devcontainer_cli="0.64.0";delete x.host_artifacts.devcontainer_cli.package_lock_json.packages["node_modules/@devcontainers/cli"].integrity;fs.writeFileSync(p,JSON.stringify(x))' "${BATS_TEST_TMPDIR}/lock.json"
    run node "${TOOL}" validate "${BATS_TEST_TMPDIR}/lock.json"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *'missing npm integrity'* ]]
}

@test "unknown lock fields cannot add a package replay contract" {
    node -e 'const fs=require("fs"),p=process.argv[1],x=JSON.parse(fs.readFileSync(p));x.packages=[];fs.writeFileSync(p,JSON.stringify(x))' "${BATS_TEST_TMPDIR}/lock.json"
    run node "${TOOL}" validate "${BATS_TEST_TMPDIR}/lock.json"
    [ "${status}" -ne 0 ]
    [[ "${output}" == *'unknown dependency lock field'* ]]
}

@test "custom repositories use selected host tools without first-party app files" {
    sed 's/0000000002$/0000000008/' "${BATS_TEST_TMPDIR}/host/parse-devcontainer.sh" > "${BATS_TEST_TMPDIR}/changed"
    mv "${BATS_TEST_TMPDIR}/changed" "${BATS_TEST_TMPDIR}/host/parse-devcontainer.sh"
    run node "${TOOL}" apply-host "${BATS_TEST_TMPDIR}/lock.json" "${BATS_TEST_TMPDIR}/host"
    [ "${status}" -eq 0 ]
    grep -q '0000000002$' "${BATS_TEST_TMPDIR}/host/parse-devcontainer.sh"
}

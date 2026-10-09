#!/bin/bash
set -o errexit
set -o nounset
set -o pipefail
export LC_ALL=C
umask 022

readonly VERSION="${1:?}"
readonly SOURCE_COMMIT="${2:?}"
readonly SOURCE_EPOCH="${3:?}"
readonly SOURCE=/source/startupscript
readonly OUTPUT=/output
readonly IMAGE="workbench_${VERSION}_x86-64.raw"
readonly BUILDER_BASE=sha256:f610ab94648195aa356059f5b41d6085c9d4d903c072430cdd1af7bdb646106b
[[ "$VERSION" =~ ^[1-9][0-9]{0,15}$ && "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ && "$SOURCE_EPOCH" =~ ^[0-9]+$ ]]
[[ "$(mksquashfs -version | head -1)" == 'mksquashfs version 4.6.1 '* ]]
TEMP_DIR="$(mktemp -d)"
readonly TEMP_DIR
trap 'rm -rf "$TEMP_DIR"' EXIT
readonly ROOT="$TEMP_DIR/root"
mkdir -p "$ROOT/usr/lib/workbench/butane" "$ROOT/usr/lib/workbench/maintenance" \
    "$ROOT/usr/lib/workbench/units" "$ROOT/usr/lib/systemd/system" "$ROOT/usr/lib/extension-release.d"
# Preserve managed links while resolving units outside systemd's unit search path.
ln -s ../../workbench/units "$ROOT/usr/lib/systemd/system/workbench"

while IFS= read -r file; do
    [[ -n "$file" && "$file" != /* && "$file" != *..* ]]
    [[ -f "$SOURCE/butane/$file" && ! -L "$SOURCE/butane/$file" ]]
    mkdir -p "$ROOT/usr/lib/workbench/butane/$(dirname "$file")"
    cp "$SOURCE/butane/$file" "$ROOT/usr/lib/workbench/butane/$file"
done < "$SOURCE/maintenance/build/payload-files.txt"

while IFS= read -r -d '' file; do
    relative="${file#"$SOURCE/maintenance/"}"
    case "$relative" in
        build/*) continue ;;
        units/*) target="$ROOT/usr/lib/workbench/units/${relative#units/}" ;;
        bootstrap/*|*.sh|*.json|*.tsv) target="$ROOT/usr/lib/workbench/maintenance/$relative" ;;
        *) echo "Unlisted maintenance input: $relative" >&2; exit 1 ;;
    esac
    [[ ! -L "$file" ]]
    mkdir -p "$(dirname "$target")"
    cp "$file" "$target"
done < <(find "$SOURCE/maintenance" -type f -print0 | sort -z)
[[ -f "$ROOT/usr/lib/workbench/maintenance/run-actions.sh" ]]
[[ -f "$ROOT/usr/lib/workbench/maintenance/actions.json" ]]
[[ -f "$ROOT/usr/lib/systemd/system/workbench/runtime/devcontainer.service" ]]
[[ -f "$ROOT/usr/lib/systemd/system/workbench/cache/devcontainer.service" ]]

PACKAGE_URL="$(jq -er '.packages["node_modules/jsonc-parser"].resolved' "$SOURCE/butane/package-lock.json")"
PACKAGE_INTEGRITY="$(jq -er '.packages["node_modules/jsonc-parser"].integrity' "$SOURCE/butane/package-lock.json")"
[[ "$PACKAGE_URL" =~ ^https://registry.npmjs.org/jsonc-parser/-/jsonc-parser-[0-9.]+.tgz$ && "$PACKAGE_INTEGRITY" == sha512-* ]]
curl --fail --silent --show-error --location --connect-timeout 10 --max-time 60 \
    "$PACKAGE_URL" -o "$TEMP_DIR/jsonc-parser.tgz"
ACTUAL_INTEGRITY="$(openssl dgst -sha512 -binary "$TEMP_DIR/jsonc-parser.tgz" | base64 -w0)"
[[ "sha512-$ACTUAL_INTEGRITY" == "$PACKAGE_INTEGRITY" ]] || { echo 'jsonc-parser integrity mismatch' >&2; exit 1; }
mkdir -p "$ROOT/usr/lib/workbench/butane/node_modules/jsonc-parser"
tar -xzf "$TEMP_DIR/jsonc-parser.tgz" --strip-components=1 \
    -C "$ROOT/usr/lib/workbench/butane/node_modules/jsonc-parser"

cat > "$ROOT/usr/lib/extension-release.d/extension-release.workbench" <<'RELEASE'
ID=flatcar
SYSEXT_LEVEL=1.0
ARCHITECTURE=x86-64
EXTENSION_RELOAD_MANAGER=1
RELEASE
jq -n --arg version "$VERSION" --arg source_commit "$SOURCE_COMMIT" \
    --argjson source_epoch "$SOURCE_EPOCH" --arg builder_base "$BUILDER_BASE" \
    '{version:$version,source_commit:$source_commit,source_epoch:$source_epoch,builder_base:$builder_base}' \
    > "$ROOT/usr/lib/workbench/release.json"
find "$ROOT" -type d -exec chmod 0755 {} +
find "$ROOT" -type f -exec chmod 0644 {} +
find "$ROOT/usr/lib/workbench" -type f \
    \( -name '*.sh' -o -name jsoncStripComments.mjs -o -name 'docker-credential-*' -o -name oem-postinst \) -exec chmod 0755 {} +
(
    cd "$ROOT"
    find usr -type f -print0 | sort -z | xargs -0 sha256sum
) > "$OUTPUT/payload.sha256"
mksquashfs "$ROOT" "$OUTPUT/$IMAGE" -noappend -all-root -no-xattrs \
    -comp gzip -b 1048576 -processors 1 -mkfs-time "$SOURCE_EPOCH" -all-time "$SOURCE_EPOCH" \
    -no-progress -quiet
(cd "$OUTPUT" && sha256sum "$IMAGE" > SHA256SUMS)
cp "$ROOT/usr/lib/workbench/release.json" "$OUTPUT/provenance.json"

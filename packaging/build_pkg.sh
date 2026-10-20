#!/bin/bash
# Builds dist/secondchair-hajung-beta.pkg (unsigned: for family and testers, not for strangers).
# The pkg holds no third-party binaries: its postinstall downloads BlackHole from the official site.
#
#   bash packaging/build_pkg.sh
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="dist/secondchair-hajung-beta.pkg"
rm -rf build && mkdir -p build dist
export COPYFILE_DISABLE=1   # no hidden ._ files in the package
xattr -cr packaging/payload 2>/dev/null || true
find packaging/payload -name "._*" -delete

pkgbuild --root packaging/payload \
         --identifier io.github.junchee.secondchair.beta \
         --version 0.1.0 \
         --scripts packaging/scripts \
         --install-location / \
         --ownership recommended \
         build/secondchair-component.pkg

productbuild --distribution packaging/distribution.xml \
             --resources packaging/resources \
             --package-path build \
             "$OUT"

echo
echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
pkgutil --check-signature "$OUT" | head -2 || true

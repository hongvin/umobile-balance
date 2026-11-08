#!/bin/bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
repo_dir="$(cd -- "$script_dir/../.." && pwd)"
build_dir="$repo_dir/build/macos"
app_path="$build_dir/U Mobile Balance.app"
mkdir -p "$app_path/Contents/MacOS" "$build_dir/module-cache"
architectures=("$(uname -m)")
if [[ "${1:-}" == "--universal" ]]; then architectures=(arm64 x86_64); fi
for architecture in "${architectures[@]}"; do
  swiftc -swift-version 5 -target "$architecture-apple-macos14.0" -O \
    -module-cache-path "$build_dir/module-cache" \
    "$script_dir"/Sources/*.swift -framework SwiftUI -framework AppKit -framework Security \
    -o "$build_dir/UMobileWidget-$architecture"
done
if [[ ${#architectures[@]} -eq 2 ]]; then
  lipo -create "$build_dir/UMobileWidget-arm64" "$build_dir/UMobileWidget-x86_64" \
    -output "$app_path/Contents/MacOS/UMobileWidget"
else
  cp "$build_dir/UMobileWidget-${architectures[0]}" "$app_path/Contents/MacOS/UMobileWidget"
fi
python3 - "$app_path/Contents/Info.plist" <<'PY'
import plistlib,sys
with open(sys.argv[1],'wb') as file:
    plistlib.dump({'CFBundleName':'U Mobile Balance','CFBundleDisplayName':'U Mobile Balance',
      'CFBundleIdentifier':'local.hongvin.umobile-widget','CFBundleExecutable':'UMobileWidget',
      'CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.1.0','CFBundleVersion':'1',
      'LSMinimumSystemVersion':'14.0','NSHighResolutionCapable':True,
      'LSMultipleInstancesProhibited':True},file)
PY
codesign --force --sign - --identifier local.hongvin.umobile-widget "$app_path"
swiftc -swift-version 5 -target "$(uname -m)-apple-macos14.0" \
  -module-cache-path "$build_dir/module-cache" \
  "$script_dir/Sources/API.swift" "$script_dir/Tests.swift" -o "$build_dir/api-tests"
"$build_dir/api-tests" > "$build_dir/test-results.json"
echo "Built $app_path and passed API tests."

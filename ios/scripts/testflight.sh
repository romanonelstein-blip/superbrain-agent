#!/usr/bin/env bash
set -euo pipefail

PROJECT="ios/SuperBrainMobile.xcodeproj"
SCHEME="SuperBrainMobile"
BUNDLE_ID="com.romanonelstein.superbrainmobile"
ARCHIVE_PATH="$RUNNER_TEMP/SuperBrainMobile.xcarchive"
EXPORT_PATH="$RUNNER_TEMP/testflight-export"
PROFILE_DIR="$HOME/Library/MobileDevice/Provisioning Profiles"
KEY_DIR="$HOME/.appstoreconnect/private_keys"
KEYCHAIN_PATH="$RUNNER_TEMP/superbrain-signing.keychain-db"
KEYCHAIN_PASSWORD="$(openssl rand -hex 24)"

required=(
  APPLE_TEAM_ID
  APP_STORE_CONNECT_ISSUER_ID
  APP_STORE_CONNECT_KEY_ID
  APP_STORE_CONNECT_PRIVATE_KEY_BASE64
  IOS_DISTRIBUTION_CERTIFICATE_P12_BASE64
  IOS_DISTRIBUTION_CERTIFICATE_PASSWORD
  IOS_PROVISIONING_PROFILE_BASE64
)

for name in "${required[@]}"; do
  if [ -z "${!name:-}" ]; then
    echo "::error::Missing required GitHub Actions secret: $name"
    exit 1
  fi
done

cleanup() {
  rm -rf "$KEY_DIR"
  rm -f "$PROFILE_DIR/"*.mobileprovision 2>/dev/null || true
  security delete-keychain "$KEYCHAIN_PATH" 2>/dev/null || true
}
trap cleanup EXIT

decode_base64() {
  python3 -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.buffer.read()))'
}

echo "Checking Xcode version..."
xcodebuild -version
XCODE_MAJOR="$(xcodebuild -version | awk '/Xcode/{split($2,a,"."); print a[1]}')"
if [ "$XCODE_MAJOR" -lt 26 ]; then
  echo "::error::App Store Connect requires this iOS build to use Xcode 26 or newer."
  exit 1
fi

CERT_PATH="$RUNNER_TEMP/distribution.p12"
PROFILE_PATH="$RUNNER_TEMP/profile.mobileprovision"
PROFILE_PLIST="$RUNNER_TEMP/profile.plist"

printf '%s' "$IOS_DISTRIBUTION_CERTIFICATE_P12_BASE64" | decode_base64 > "$CERT_PATH"
printf '%s' "$IOS_PROVISIONING_PROFILE_BASE64" | decode_base64 > "$PROFILE_PATH"

security create-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$KEYCHAIN_PASSWORD" "$KEYCHAIN_PATH"
security list-keychains -d user -s "$KEYCHAIN_PATH"
security import "$CERT_PATH"   -k "$KEYCHAIN_PATH"   -P "$IOS_DISTRIBUTION_CERTIFICATE_PASSWORD"   -T /usr/bin/codesign   -T /usr/bin/security
security set-key-partition-list   -S apple-tool:,apple:,codesign:   -s   -k "$KEYCHAIN_PASSWORD"   "$KEYCHAIN_PATH"
security find-identity -v -p codesigning "$KEYCHAIN_PATH"

security cms -D -i "$PROFILE_PATH" > "$PROFILE_PLIST"
PROFILE_UUID="$(/usr/libexec/PlistBuddy -c 'Print :UUID' "$PROFILE_PLIST")"
PROFILE_NAME="$(/usr/libexec/PlistBuddy -c 'Print :Name' "$PROFILE_PLIST")"
PROFILE_TEAM="$(/usr/libexec/PlistBuddy -c 'Print :TeamIdentifier:0' "$PROFILE_PLIST")"
PROFILE_APP_ID="$(/usr/libexec/PlistBuddy -c 'Print :Entitlements:application-identifier' "$PROFILE_PLIST")"
PROFILE_BUNDLE_ID="${PROFILE_APP_ID#*.}"

if [ "$PROFILE_TEAM" != "$APPLE_TEAM_ID" ]; then
  echo "::error::Provisioning profile belongs to a different Apple Team."
  exit 1
fi
if [ "$PROFILE_BUNDLE_ID" != "$BUNDLE_ID" ]; then
  echo "::error::Provisioning profile bundle ID does not match $BUNDLE_ID."
  exit 1
fi

mkdir -p "$PROFILE_DIR"
cp "$PROFILE_PATH" "$PROFILE_DIR/$PROFILE_UUID.mobileprovision"

mkdir -p "$KEY_DIR"
ASC_KEY_PATH="$KEY_DIR/AuthKey_${APP_STORE_CONNECT_KEY_ID}.p8"
printf '%s' "$APP_STORE_CONNECT_PRIVATE_KEY_BASE64" | decode_base64 > "$ASC_KEY_PATH"
chmod 600 "$ASC_KEY_PATH"

rm -rf "$ARCHIVE_PATH" "$EXPORT_PATH"

xcodebuild   -project "$PROJECT"   -scheme "$SCHEME"   -configuration Release   -destination 'generic/platform=iOS'   -archivePath "$ARCHIVE_PATH"   DEVELOPMENT_TEAM="$APPLE_TEAM_ID"   CODE_SIGN_STYLE=Manual   CODE_SIGN_IDENTITY="Apple Distribution"   PROVISIONING_PROFILE_SPECIFIER="$PROFILE_NAME"   CURRENT_PROJECT_VERSION="${GITHUB_RUN_NUMBER:-1}"   archive

METHOD="app-store-connect"
if ! xcodebuild -help 2>&1 | grep -q "app-store-connect"; then
  METHOD="app-store"
fi

EXPORT_OPTIONS="$RUNNER_TEMP/ExportOptions.plist"
cat > "$EXPORT_OPTIONS" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key>
  <string>$METHOD</string>
  <key>destination</key>
  <string>export</string>
  <key>signingStyle</key>
  <string>manual</string>
  <key>teamID</key>
  <string>$APPLE_TEAM_ID</string>
  <key>provisioningProfiles</key>
  <dict>
    <key>$BUNDLE_ID</key>
    <string>$PROFILE_NAME</string>
  </dict>
  <key>stripSwiftSymbols</key>
  <true/>
  <key>uploadSymbols</key>
  <true/>
</dict>
</plist>
PLIST

xcodebuild   -exportArchive   -archivePath "$ARCHIVE_PATH"   -exportPath "$EXPORT_PATH"   -exportOptionsPlist "$EXPORT_OPTIONS"

IPA="$(find "$EXPORT_PATH" -maxdepth 1 -name '*.ipa' -print -quit)"
if [ -z "$IPA" ]; then
  echo "::error::No exported IPA was produced."
  exit 1
fi

echo "Validating IPA with App Store Connect..."
xcrun altool --validate-app   -f "$IPA"   -t ios   --apiKey "$APP_STORE_CONNECT_KEY_ID"   --apiIssuer "$APP_STORE_CONNECT_ISSUER_ID"

echo "Uploading IPA to App Store Connect / TestFlight..."
xcrun altool --upload-app   -f "$IPA"   -t ios   --apiKey "$APP_STORE_CONNECT_KEY_ID"   --apiIssuer "$APP_STORE_CONNECT_ISSUER_ID"

echo "TestFlight upload submitted successfully."

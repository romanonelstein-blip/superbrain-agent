# SuperBrain iOS: TestFlight without a Mac

The repository contains a manual GitHub Actions workflow at
`.github/workflows/ios-testflight.yml`.

It builds on GitHub's `macos-26` runner, requires Xcode 26 or newer, signs
`com.romanonelstein.superbrainmobile`, validates the exported IPA with
App Store Connect, and uploads it to TestFlight.

## One-time Apple setup

Apple requires an App Store Connect app record before a build can be
uploaded. The app record must use bundle ID
`com.romanonelstein.superbrainmobile`.

The signing account must be an eligible Apple Developer Program account.
Do not bypass Apple's age, identity, or account-holder requirements; use an
eligible account holder or organization where required.

Create or obtain an Apple Distribution certificate and an App Store
Connect provisioning profile for that bundle ID, plus an App Store Connect
team API key with sufficient access for build upload.

## GitHub Actions secrets

Add these repository secrets. Never commit their values:

- `APPLE_TEAM_ID`
- `APP_STORE_CONNECT_ISSUER_ID`
- `APP_STORE_CONNECT_KEY_ID`
- `APP_STORE_CONNECT_PRIVATE_KEY_BASE64`
- `IOS_DISTRIBUTION_CERTIFICATE_P12_BASE64`
- `IOS_DISTRIBUTION_CERTIFICATE_PASSWORD`
- `IOS_PROVISIONING_PROFILE_BASE64`

The private `.p8`, distribution `.p12`, and provisioning profile are
stored as base64 strings so multiline/binary content never needs to be
committed.

## Running the upload

Open GitHub Actions, select **iOS TestFlight upload (manual)**, and run the
workflow on `sb-ios-cloud-build`.

The workflow intentionally stops before upload if any required secret is
missing or if the provisioning profile bundle ID does not match the app.

## CI verification

The regular iOS workflow verifies this branch on macOS 26 / Xcode 26 before any TestFlight signing run is attempted.

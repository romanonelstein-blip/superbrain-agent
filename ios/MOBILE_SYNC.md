# SuperBrain ↔ iOS synchronization policy

The iOS app is a first-class SuperBrain client. Mobile-visible behavior is
defined in `shared/superbrain-mobile-contract.json`.

## Rule

Whenever SuperBrain gains a new version or a function that should be usable
or visible on iPhone:

1. add or update the capability in the shared contract;
2. implement the native iOS integration when the capability is required;
3. run `npm run ios:sync`;
4. commit the generated Swift contract together with the runtime change.

Required capabilities may not be marked unsupported. The Mobile Contract
Gate fails when the generated client is stale, an endpoint is missing from
`MissionAPI.swift`, the Xcode marketing version differs from the contract,
or a required capability is not native.

The regular iOS build also watches SuperBrain runtime paths. This means a
runtime/package/mobile-contract change automatically revalidates the iOS
client on macOS/Xcode before release.

The server may additionally return `superBrainVersion`, `apiVersion`
and `capabilities` from `/api/system/status`. The iOS app accepts these
fields when present and visibly warns when the connected runtime is missing
a capability required by the bundled mobile contract.

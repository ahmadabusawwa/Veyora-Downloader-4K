# Update trust and release procedure

Status: implemented and fixture-tested; production activation and Windows installation remain release gates.

The updater checks GitHub Releases in a background thread. Stable is the default; drafts are excluded. Numeric version comparison handles 2.9 < 2.10 and alpha/beta/rc prereleases. New releases need `update-manifest.json` and `update-manifest.sig`. The raw JSON bytes are verified using Ed25519 against a public key compiled into `updater/core.py`, then checked for repository, platform, release version, expiry, exact filename, size and SHA-256. Only GitHub release URLs for this repository are accepted; redirects may go to GitHub's release-assets host. Metadata and payload sizes are bounded. Inert fixtures are used in tests; no downloaded test executable is run.

`TRUSTED_KEYS` is deliberately empty. The application refuses untrusted updates until the owner supplies an offline-controlled public key. A checksum alongside an executable does not provide authenticity. No production private key was generated or embedded during development.

## Owner provisioning (before release)

1. Create an Ed25519 signing key offline using a trusted cryptographic tool. Keep its private PEM outside the repository, build machine and application. Back it up securely.
2. Export the raw 32-byte public key, base64 encode it, and add it under a stable key ID to `TRUSTED_KEYS` in `updater/core.py`. Review this trust change separately. Keep old trusted public keys during rotation; sign the next bootstrap release with a previously trusted key.
3. Build and test the Windows Setup. Review the source commit and installer hash. Optionally add Windows Authenticode signing for publisher reputation; Ed25519 metadata is the updater's independent trust mechanism.
4. On the offline signing machine, run `python tools/sign_update.py Veyora-Pro-Setup-2.0.0.exe --key /outside/repo/private.pem --key-id OWNER_KEY_ID --tag v2.0.0`. The tool signs the exact bytes; upload the installer and both metadata files together only after owner approval. Never upload the PEM.
5. Trial the process with a newer beta version and a separate TEST key in a disposable build. Turn on prereleases only in that test build. Verify cancellation, corrupted assets, forged metadata, expired manifests, offline startup and installation on Windows.

## Installation and data

The user must approve installation. Active queue tasks and local processing block installation. Settings, history and config are copied to `.veyora/backups/TIMESTAMP` before handoff. Models and downloads stay outside the application directory. A separate instance waits up to two minutes for the original PID to exit, re-verifies signature/hash, starts the installer without a shell, then exits so it does not keep the installed binaries locked. A journal records handoff; the next application launch confirms the running version or offers a retry notice. A failed verification never executes the asset.

Inno Setup uses a stable AppId and per-user directory. It does not delete user data on uninstall. This is not a transactional power-loss rollback engine. Keep the previous verified installer for manual binary recovery. `python tools/recover_settings.py BACKUP NEW_DIRECTORY` recovers a separate settings copy without overwriting current data; validate it before selecting it via `VEYORA_CONFIG_DIR`.

Existing 1.7 portable executables have no updater: users must install the first 2.x bootstrap manually. Their existing `~/.veyora` directory is reused. Future 2.x updates use the signed channel. Cross-version migration and installer failure recovery still require Windows testing.

## Remaining security gates

- Production key enrollment and custody; no private key or signing service is included.
- Windows end-to-end installer/update, power loss, cancelled setup and concurrent-process testing.
- FFmpeg distribution-specific license/source obligations and owner review of every model license.
- Local same-user malware can modify application files or staging files; this is not an OS privilege boundary. A Windows publisher signature is recommended in addition to metadata signatures.

# Public repository publication checklist

This checklist is for publishing the source repository, not a binary desktop release.

## Before changing the repository visibility

- [ ] Enable GitHub private vulnerability reporting and assign a maintainer to monitor it.
- [ ] Confirm the GitHub repository description, topics, homepage and contact/maintainer identity.
- [ ] Review the full Git history for accidentally committed secrets. The source ZIP supplied for this review contains only an initial commit, so it does not establish that the remote repository history is clean.
- [ ] Confirm that all screenshots, fixtures, fonts, icons and third-party assets may be redistributed. The README demo and test fixtures are authored project fixtures; retain provenance for any later additions.
- [ ] Confirm MIT licensing is intended and that `THIRD_PARTY_LICENSES.md` remains accurate.
- [ ] Run the complete test suite on a machine with Python, Tesseract, Chromium and Node/React dependencies installed; record skipped tests separately.
- [ ] Run the GitHub Actions workflows and fix failures before tagging a release.
- [ ] Keep the release labelled as a source preview. Do not promise a packaged desktop installer or signed binaries.

## Before a desktop binary release

- [ ] Implement bounded IPC frames and robust child-process shutdown/restart in the Tauri relay.
- [ ] Package the Python sidecar and its runtime dependencies.
- [ ] Test install and launch on a clean Windows VM without the development toolchain.
- [ ] Verify the app's filesystem access, process lifecycle, error handling and update path.
- [ ] Decide whether to sign binaries; if unsigned, label them clearly.
- [ ] Add packaged-app E2E tests and publish platform-specific checksums.

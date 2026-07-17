# Xyna TUI Progress Tracker

## Progress
- [x] Analyze requirements and sample outputs in repository files
- [x] Scaffold Python/Textual project structure
- [x] Implement fixture-backed mock gateway
- [x] Implement parser layer for table and text outputs
- [x] Implement TUI with main operational views
- [x] Add unit tests and e2e tests using the mock gateway
- [x] Execute test suite in this environment and fix failures
- [x] Expand test suite depth for fixture parsing and TCP gateway protocol handling
- [x] Add details modal split with runtime dependencies and content-by-type
- [x] Add object selection modal before object dependency trees
- [ ] Re-run full local and container validation after semantic split

## Open Tasks
1. Run local test suite and resolve any regressions.
2. Run container test suite and verify parity with local results.
3. Smoke-test live details and object-selection flows against container Xyna.
4. Add mutating command workflows with confirmation dialogs.
5. Add audit logging for write and destructive operations.

## Test Status
- Current suite: pending re-run after semantic split changes.
- Added coverage areas:
	- Fixture command extraction edge cases.
	- Parser edge/fallback behavior for malformed and partial input.
	- TCP protocol gateway encoding/status handling without live network dependency.
	- Service semantic split for dependencies vs content and object selection type mapping.

# A TUI application for Xyna Factory

Running on the same host/in the same container as Xyna Factory. Communicating with the Factory using the TCP socket on localhost:4242 with the framing documented in [docs/reference/factory-call.txt](docs/reference/factory-call.txt).

## Status
Show the current status of the Factory

## Workspace Mgmt
Show the current state of all Workspaces and allow Managament of Workspaces. Allows discovery of Problems with deploymentitems for each Workspace.

## Application Mgmt
Show the current state of all Applications and allow Managament of Applications. Allows discovery of Problems with deploymentitems for each Application.

## Xyna Property Mgmt
Show the current state of all Xnya Properties and allow Managament of Xnya Properties 

## Implementation (This Repository)

The project now contains a Python + Textual implementation with:

- A multi-view TUI for dashboard, workspaces, applications, properties, dependencies, deployment item details, triggers, and filters.
- A fixture-backed mock gateway that uses the captured example outputs under `fixtures/xyna-cli/`.
- A TCP gateway that speaks the protocol documented in `docs/reference/factory-call.txt`.
- Unit tests for parsers and service behavior.
- End-to-end Textual tests using the mock gateway.
- Split-pane, navigable detail screens for workspaces and applications.
- A GitHub Actions workflow that builds a one-file Linux binary artifact with PyInstaller.

Source layout:

- `src/xyna_tui/app.py`: Textual app and view wiring.
- `src/xyna_tui/gateway.py`: mock and TCP gateways.
- `src/xyna_tui/parsers.py`: output parsers.
- `src/xyna_tui/service.py`: app-facing domain service.
- `fixtures/xyna-cli/`: captured Xyna CLI transcripts used by the mock gateway and parser tests.
- `docs/reference/`: protocol notes and raw CLI help/reference material.
- `tests/unit/`: parser and service unit tests.
- `tests/e2e/`: end-to-end Textual tests.
- `.github/workflows/build-binary.yml`: CI build for the single-file Linux binary artifact.

## Keybindings

- `r`: Refresh active data.
- `d`: Show runtime-context dependency tree (workspace/application row).
- `i`: Show selected workspace/application details in navigable split-pane tables.
- `o`: Open object picker and show dependency tree for selected object.
- `/` (in details modals): Focus the item filter field.
- `Tab` / `Shift+Tab` (in detail modals): move focus between detail tables.
- `Esc` or `q` (in modals): close modal.

## Details UX

Workspace details (`i` on Workspaces tab):
- Top-left: summary table (state, dependency count, content summary by type).
- Top-right: runtime-context dependency tree.
- Bottom-left: content item list for the selected workspace, including type and status, with a filter field.
- Bottom-right: deployment item details for the selected content item.
- The filter field can be reached with `Tab` or `/`.

Application details (`i` on Applications tab):
- Top-left: summary table (state, dependency count, content summary by type).
- Top-right: runtime-context dependency tree (dependencies of selected application runtime context).
- Bottom-left: content item list for the selected application, including type and status, with a filter field.
- Bottom-right: deployment item details for the selected item.
- The filter field can be reached with `Tab` or `/`.

All tables are keyboard-navigable with arrow keys; `Tab` and `Shift+Tab` switch active table.

Dependencies tab:
- Shows runtime-context dependencies as expanded transitive trees down to leaf applications/contexts.

Details modals:
- Workspace and application detail screens also show runtime-context dependencies as expanded transitive trees.

Deployment item details are available directly in workspace/application details views, based on the selected context and selected content item.

## Run

1. Install dependencies:

```bash
pip install -e .[dev]
```

2. Run with mock data (default):

```bash
xyna-tui
```

3. Run against real Xyna Factory TCP endpoint:

```bash
XYNA_TUI_USE_MOCK=0 XYNA_TUI_HOST=127.0.0.1 XYNA_TUI_PORT=4242 xyna-tui
```

## Tests

```bash
pytest -q
```

Screenshot regression artifacts are written by the e2e screenshot test to [test-results/screenshots](test-results/screenshots).

## CI Binary Build

GitHub Actions can build a single-file Linux binary with PyInstaller and upload it as a workflow artifact:

- Workflow: `.github/workflows/build-binary.yml`
- Output binary: `dist/xyna-tui`
- Artifact name: `xyna-tui-linux-binary`

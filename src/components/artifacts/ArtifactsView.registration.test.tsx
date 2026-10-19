// @vitest-environment jsdom
import type { ReactNode } from "react"
import { afterEach, beforeEach, expect, test, vi } from "vitest"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import ArtifactsView from "./ArtifactsView"
import type { ArtifactRecord } from "@/lib/transport"

const mocks = vi.hoisted(() => ({
  listArtifacts: vi.fn(),
  getArtifact: vi.fn(),
  listArtifactVersions: vi.fn(),
  reset: vi.fn(),
  transitionTo: vi.fn(),
  drag: vi.fn(),
  viewerRef: { current: null },
  t: (key: string) => key,
  returned: null as unknown as ArtifactRecord,
}))
vi.mock("@/lib/transport-provider", () => ({ getTransport: () => mocks }))
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mocks.t }) }))
vi.mock("@/hooks/useDragWidth", () => ({ useDragWidth: () => mocks.drag }))
vi.mock("@/hooks/useFullscreenTransition", () => ({
  useFullscreenTransition: () => ({
    ref: mocks.viewerRef,
    reset: mocks.reset,
    transitionTo: mocks.transitionTo,
    animating: false,
  }),
}))
vi.mock("@/components/chat/files/FileActionMenu", () => ({
  FileContextMenu: ({ children }: { children: ReactNode }) => children,
}))
vi.mock("@/components/chat/files/useFileResource", () => ({
  useFileResource: (_target: unknown, options?: { onPreviewFile?: () => void }) => ({
    primary: "preview",
    run: () => options?.onPreviewFile?.(),
  }),
}))
vi.mock("./ArtifactViewer", () => ({ default: () => <div>Managed preview</div> }))
vi.mock("./ArtifactRegistrationDialog", () => ({
  ArtifactRegistrationDialog: ({
    artifact,
    onImported,
  }: {
    artifact?: ArtifactRecord
    onImported: (artifact: ArtifactRecord) => void
  }) => (
    <div>
      {artifact && (
        <p>
          Target {artifact.id} v{artifact.currentVersion}
        </p>
      )}
      <button onClick={() => onImported(mocks.returned)}>complete registration</button>
    </div>
  ),
}))

const saved: ArtifactRecord = {
  id: "artifact-new",
  title: "Registered report",
  kind: "report",
  contentType: "html",
  lifecycleState: "active",
  privacy: "local_private",
  currentVersion: 1,
  currentHash: "a".repeat(64),
  payloadKind: "freeform",
  sourceCount: 0,
  sourceSummaries: [],
  evidenceSummary: {},
  capabilities: {},
  projectPath: "/managed/new",
  createdAt: "2026-10-19T00:00:00Z",
  updatedAt: "2026-10-19T00:00:00Z",
}

beforeEach(() => {
  window.localStorage?.clear()
  mocks.listArtifacts.mockReset()
  mocks.getArtifact.mockReset().mockResolvedValue(saved)
  mocks.listArtifactVersions.mockReset().mockResolvedValue([])
  mocks.returned = saved
})
afterEach(cleanup)

test("registration selects its durable result and ignores a pre-registration list response", async () => {
  let finishOld!: (rows: ArtifactRecord[]) => void
  mocks.listArtifacts
    .mockReturnValueOnce(
      new Promise((resolve) => {
        finishOld = resolve
      }),
    )
    .mockResolvedValue([saved])
  render(<ArtifactsView isViewVisible />)
  fireEvent.click(screen.getByRole("button", { name: "artifacts.registration.create" }))
  fireEvent.click(screen.getByRole("button", { name: "complete registration" }))
  await screen.findAllByText("Registered report")
  await act(async () => finishOld([]))
  expect(screen.getAllByText("Registered report")).toHaveLength(2)
  expect(screen.getAllByText("artifacts.registration.firstVersion")).toHaveLength(2)
  expect(mocks.getArtifact).toHaveBeenCalledWith("artifact-new")
})

test("update is bound to the selected version and refreshes it without a duplicate library row", async () => {
  const current = { ...saved, id: "existing", title: "Existing report", currentVersion: 5 }
  const next = { ...current, currentVersion: 6 }
  mocks.listArtifacts.mockResolvedValue([current])
  mocks.getArtifact.mockResolvedValue(current)
  render(<ArtifactsView isViewVisible />)
  fireEvent.click(await screen.findByRole("button", { name: /Existing report/ }))
  fireEvent.click(await screen.findByRole("button", { name: "artifacts.registration.update" }))
  expect(screen.getByText("Target existing v5")).toBeTruthy()
  mocks.returned = next
  mocks.listArtifacts.mockResolvedValue([next])
  mocks.getArtifact.mockResolvedValue(next)
  fireEvent.click(screen.getByRole("button", { name: "complete registration" }))
  await waitFor(() => expect(screen.getByText("v6")).toBeTruthy())
  expect(screen.getAllByText("Existing report")).toHaveLength(2)
  expect(screen.getAllByText("artifacts.registration.updatedVersion")).toHaveLength(2)
  expect(current.currentVersion).toBe(5)
})

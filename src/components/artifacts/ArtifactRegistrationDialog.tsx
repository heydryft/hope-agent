import { useEffect, useRef, useState } from "react"
import { useTranslation } from "react-i18next"
import { Check, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { getTransport, useTransport } from "@/lib/transport-provider"
import type { ArtifactRecord } from "@/lib/transport"

/** Owner action only: an explicit source file becomes a managed snapshot.
 * Updates keep the selected identity and exact optimistic-concurrency version. */
export function ArtifactRegistrationDialog({
  artifact,
  onImported,
  onClose,
}: {
  artifact?: ArtifactRecord
  onImported: (artifact: ArtifactRecord) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const transport = useTransport()
  const [originalTransport] = useState(() => transport)
  const [filePath, setFilePath] = useState("")
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "failed">("idle")
  const [error, setError] = useState(false)
  const lifecycle = useRef<{ active: boolean; timer?: ReturnType<typeof setTimeout> }>({
    active: true,
  })
  useEffect(() => {
    const state = lifecycle.current
    state.active = true
    return () => {
      state.active = false
      clearTimeout(state.timer)
    }
  }, [])

  const hostChanged = originalTransport !== transport
  const locked = status === "saving" || status === "saved"
  const path = filePath.trim()
  const absolute = path.startsWith("/") || /^[a-z]:[\\/]/i.test(path) || path.startsWith("\\\\")
  const label = t(artifact ? "artifacts.registration.update" : "artifacts.registration.create")

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (!absolute || status !== "idle" || hostChanged) return
    setStatus("saving")
    setError(false)
    let saved: ArtifactRecord
    try {
      saved = await originalTransport.importArtifact({
        filePath: path,
        ...(artifact
          ? { artifactId: artifact.id, expectedVersion: artifact.currentVersion }
          : { privacy: "local_private" }),
      })
    } catch {
      if (!lifecycle.current.active) return
      setError(true)
      setStatus("failed")
      lifecycle.current.timer = setTimeout(() => setStatus("idle"), 2000)
      return
    }
    if (!lifecycle.current.active) return
    if (getTransport() !== originalTransport) {
      setError(true)
      setStatus("failed")
      lifecycle.current.timer = setTimeout(() => setStatus("idle"), 2000)
      return
    }
    // A successful write remains successful even if a later view refresh fails.
    setStatus("saved")
    onImported(saved)
    lifecycle.current.timer = setTimeout(onClose, 2000)
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !locked) onClose()
      }}
    >
      <DialogContent className="max-w-lg" showCloseButton={!locked}>
        <form onSubmit={(event) => void save(event)} className="space-y-4">
          <DialogHeader>
            <DialogTitle>{label}</DialogTitle>
            <DialogDescription>{t("artifacts.registration.description")}</DialogDescription>
          </DialogHeader>
          {artifact && (
            <p className="break-all text-sm">
              {artifact.title} · v{artifact.currentVersion}
            </p>
          )}
          <label className="block space-y-2 text-sm">
            {t("artifacts.registration.path")}
            <Input
              value={filePath}
              onChange={(event) => setFilePath(event.target.value)}
              disabled={locked || hostChanged}
              aria-label={t("artifacts.registration.path")}
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          {(error || hostChanged) && (
            <p role="alert" className="text-sm text-destructive">
              {t(
                hostChanged
                  ? "artifacts.registration.hostChanged"
                  : "artifacts.registration.failed",
              )}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="secondary" onClick={onClose} disabled={locked}>
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              disabled={!absolute || status !== "idle" || hostChanged}
              variant={
                status === "failed" ? "destructive" : status === "saved" ? "outline" : "default"
              }
            >
              {status === "saving" && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {status === "saved" && <Check className="mr-1.5 h-4 w-4 text-green-600" />}
              {status === "saving"
                ? t("common.saving")
                : status === "saved"
                  ? t("common.saved")
                  : status === "failed"
                    ? t("common.retry")
                    : label}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

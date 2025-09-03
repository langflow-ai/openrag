"use client"

import { useCallback, useState } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

// declare globals to silence TS
declare global {
  interface Window { google?: any; gapi?: any }
}

const loadScript = (src: string) =>
  new Promise<void>((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) return resolve()
    const s = document.createElement("script")
    s.src = src
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => reject(new Error(`Failed to load ${src}`))
    document.head.appendChild(s)
  })

export type DriveSelection = { files: string[]; folders: string[] }

export function GoogleDrivePicker({
  value,
  onChange,
  buttonLabel = "Choose in Drive",
}: {
  value?: DriveSelection
  onChange: (sel: DriveSelection) => void
  buttonLabel?: string
}) {
  const [loading, setLoading] = useState(false)

  const ensureGoogleApis = useCallback(async () => {
    await loadScript("https://accounts.google.com/gsi/client")
    await loadScript("https://apis.google.com/js/api.js")
    await new Promise<void>((res) => window.gapi?.load("picker", () => res()))
  }, [])

  const openPicker = useCallback(async () => {
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID
    const apiKey = process.env.NEXT_PUBLIC_GOOGLE_API_KEY
    if (!clientId || !apiKey) {
      alert("Google Picker requires NEXT_PUBLIC_GOOGLE_CLIENT_ID and NEXT_PUBLIC_GOOGLE_API_KEY")
      return
    }
    try {
      setLoading(true)
      await ensureGoogleApis()
      const tokenClient = window.google.accounts.oauth2.initTokenClient({
        client_id: clientId,
        scope: "https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/drive.metadata.readonly",
        callback: (tokenResp: any) => {
          const viewDocs = new window.google.picker.DocsView()
            .setIncludeFolders(true)
            .setSelectFolderEnabled(true)

          console.log("Picker using clientId:", clientId, "apiKey:", apiKey)

          const picker = new window.google.picker.PickerBuilder()
            .enableFeature(window.google.picker.Feature.MULTISELECT_ENABLED)
            .setOAuthToken(tokenResp.access_token)
            .setDeveloperKey(apiKey)
            .addView(viewDocs)
            .setCallback((data: any) => {
              if (data.action === window.google.picker.Action.PICKED) {
                const pickedFiles: string[] = []
                const pickedFolders: string[] = []
                for (const doc of data.docs || []) {
                  const id = doc.id
                  const isFolder = doc?.type === "folder" || doc?.mimeType === "application/vnd.google-apps.folder"
                  if (isFolder) pickedFolders.push(id)
                  else pickedFiles.push(id)
                }
                onChange({ files: pickedFiles, folders: pickedFolders })
              }
            })
            .build()
          picker.setVisible(true)
        },
      })
      tokenClient.requestAccessToken()
    } catch (e) {
      console.error("Drive Picker error", e)
      alert("Failed to open Google Drive Picker. See console.")
    } finally {
      setLoading(false)
    }
  }, [ensureGoogleApis, onChange])

  const filesCount = value?.files?.length ?? 0
  const foldersCount = value?.folders?.length ?? 0

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" onClick={openPicker} disabled={loading}>
          {loading ? "Loading Picker…" : buttonLabel}
        </Button>
        {(filesCount > 0 || foldersCount > 0) && (
          <Badge variant="outline">{filesCount} file(s), {foldersCount} folder(s) selected</Badge>
        )}
      </div>

      {(filesCount > 0 || foldersCount > 0) && (
        <div className="flex flex-wrap gap-1 max-h-20 overflow-auto">
          {value!.files.slice(0, 6).map((id) => <Badge key={id} variant="secondary">file:{id}</Badge>)}
          {filesCount > 6 && <Badge>+{filesCount - 6} more</Badge>}
          {value!.folders.slice(0, 6).map((id) => <Badge key={id} variant="secondary">folder:{id}</Badge>)}
          {foldersCount > 6 && <Badge>+{foldersCount - 6} more</Badge>}
        </div>
      )}
    </div>
  )
}

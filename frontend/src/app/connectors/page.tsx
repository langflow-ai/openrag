import React, { useState } from "react";
import { GoogleDrivePicker, type DriveSelection } from "./GoogleDrivePicker"

const [driveSelection, setDriveSelection] = useState<DriveSelection>({ files: [], folders: [] });

// in JSX
<GoogleDrivePicker value={driveSelection} onChange={setDriveSelection} />

// when calling sync:
const body: { file_ids: string[]; folder_ids: string[]; recursive: boolean } = {
  file_ids: driveSelection.files,
  folder_ids: driveSelection.folders,
  recursive: true,
};

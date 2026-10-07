# Downloads

Data → Downloads provides files from the configured main directory including subdirectories for logged-in server manager users. Main directory: Settings → Server & Module Paths → Downloads. Default: `/srv/server-manager/downloads`. Select the existing data folder, verify changes, and activate via the settings page. Existing data folders are not automatically released, created, or copied.

Folder navigation, breadcrumbs, search in current folder, file size, change date, and 100 entries per page. Individual files are streamed as downloads; HTTP Range supports resumptions. No upload, modification, or deletion function is available. Hidden files and path components, symbolic links, hardlinks, and special files are not offered. Directory accesses open each path component without following symlinks; a subsequent path substitution does not redirect an already opened transfer.

Downloads require the existing login session. This is not public file sharing nor user/group permission management. All logged-in server manager users can read the offered files. The service reads with its own file permissions. Therefore, restrict the main directory specifically to the data set to be provided.

During active file transfers, downloads register as sleep blockers and prevent restarts via the path settings. Changes to the main folder follow the existing bookmarking/restart schedule.

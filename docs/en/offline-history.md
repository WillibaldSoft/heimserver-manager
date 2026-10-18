# Offline recovery copies

New server-side recovery copies are stored beside the source in
`.hsm-history/<UTC timestamp>-<unique ID>/<original filename>`.
Full original filenames are retained. The reserved `.hsm-` prefix excludes the
folder from file listings and synchronization.
SMB deletions and HTTPS replacements move the original inode, retaining its
owner, file permissions and ACLs. SMB replacements still use the verified ACL
copy; insufficient permissions are not bypassed. Directories follow the share's
creation and inheritance rules. Legacy copies without an original-name mapping
retain their old names when moved. No automatic deletion or retention expiry.
Linux clients must reload the updated SMB component (quit fully and reopen).
Available from Manager 0.13-7 and Linux client 0.4.40. Earlier packages remain unchanged.

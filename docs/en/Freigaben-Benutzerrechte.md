# User Permissions Per Share

Call: **Shares → User Permissions** (`/freigaben/rechte`).

The SMB matrix shows shares in rows and users/groups in columns: no access, read-only, read/write, SMB admin, or ambiguous. Clicking a share reveals the origin of rules and POSIX permissions for the root folder. Clicking a permission opens modification for that specific account. A filter selection limits the overview to one user or group; additional local or domain accounts can be added in the share view.

The evaluation reads `testparm -s`, considers share standards and known NSS group memberships. `invalid users` takes precedence over permissions; `write list` takes precedence over `read list`. An empty `valid users` does not mean "nobody", but rather all authenticated accounts in principle. Dynamic names/netgroups and non-resolvable account assignments are not represented as secure access. Group columns show group rules, not the sum of a user's memberships.

## Changes

- **No Access:** targeted Samba block, even against a group permission.
- **Read / Read and Write:** specific rule. A conflict with a more extensive group rule is rejected before application and explained; group memberships are not automatically changed.
- **SMB Admin:** file operations as root; additional confirmation required.
- **Groups/Standard:** remove direct rules. The last permission of an otherwise restricted share must not be converted into an empty list, because that would expand access.

Unrelated rules and share options remain intact. A change runs via the existing session-bound preview, configuration backup, validation, and activation. Configuration dependencies and relevant group resolution are re-checked before writing.

Active guest access is displayed separately: a user block does not prevent independent anonymous login. Existing SMB connections should be disconnected and rebuilt after permission changes.

## Folder Permissions and NFS

POSIX permissions of the root folder can optionally be adjusted accordingly. This is not a recursive change to existing subfolders or files. Inheritance for future new content is selectable separately. A file identity forced by `force user/group` is displayed; automatic personal ACL adjustments are then rejected, except for the matching forced group.

NFS shows export rules and offers targeted adjustment of the root folder ACL for resolvable users/groups. The numeric UID/GID of the client remains decisive; a read-only export stays read-only. A group-ACL entry `---` does not prevent access from other groups. Root access cannot be restricted via this ACL interface.

ACL changes affect the same folder also across other SMB/NFS shares. The preview lists these shares. Previous ACLs are additionally stored in `acl-before.json` in the respective share backup directory. Failed activations revert configuration and ACL. Changed folder identities or ACLs require a new preview. Write access uses an opened directory descriptor without symlink following. When expanding the ACL mask, previously masked rights of other entries are not inadvertently granted.

The displayed folder check concerns POSIX permissions of the root folder. Authentication, parent directories, Windows ACLs, forced identities and individual file permissions can additionally restrict actual usable access.

## Validation

`python3 -m unittest discover -s tests -p 'test_share*.py' -v`

56 tests: share regressions, group resolution/priorities, conflicts, last permission, admin confirmation, guest access, targeted changes, form protection, preview, actual ACL application and rollback, masks and competing changes. Productive permissions are not changed by tests or activation of the module.

Reference: [Samba smb.conf – Access Lists](https://www.samba.org/samba/docs/current/man-html/smb.conf.5.html).

# Users, Linux groups and passwords

Manage local accounts under Shares & Users → Users → Edit user. Settings →
Manager Users links each Linux account to the same editor. The overview shows
existing groups; the editor also shows UID/GID, home, shell and primary group.

Only Manager administrators may make changes. Confirm your own current
administrator password before every change. Local accounts with UID 1000 to
59999 are supported; root and system accounts below UID 1000 are excluded.
UID, primary group, home and shell are not changed.

Add or remove groups individually. Other memberships remain unchanged, including
memberships that were not visible in earlier selection lists. sudo and other
groups with extensive privileges require explicit confirmation. sudo grants
operating-system administration but does not grant Manager access. Groups such
as docker and disk can also grant substantial privileges. Existing user sessions
require a new login afterwards. Changes within the Manager are serialized;
stale forms are rejected using account identity and current memberships.

Linux and SMB passwords are separate actions. Enter the new password twice:
8 to 256 characters without line breaks. Linux password changes also affect
approved PAM logins to the Manager and invalidate their existing sessions.
Setting a password may re-enable a locked Linux password; SSH keys and account
expiry rules remain separate. Setting an SMB password enables Samba access if
needed. It does not change the Linux password or share permissions. NFS does not
have a separate user password.

Passwords are passed only through system tools' standard input, never as process
arguments or shell text. The Manager does not store them in plain text or display
them again. Password errors do not return unfiltered external-tool output.
Operating-system and Samba password databases continue to store their own
protected credentials. Appropriate service privileges and chpasswd or smbpasswd
are required; missing tools or password-policy failures are reported as unconfirmed.

Group selection: check or uncheck memberships and apply them together with “Save groups”. The primary group is protected; the administrator password and explicit confirmation for changes to privileged groups are required. Stale group selections are rejected.

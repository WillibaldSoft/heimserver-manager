# Publication and Data Privacy – Version 0.12-64

Publication is built from an explicit file list, not from all files of the
running server. DEB, source archive, and complete ZIP contain no local Git history,
configuration, database, backup, or login profiles.
The included file packaging/debian/server-manager.env is a neutral package template;
it is not a copy of a local .env file.

Before release, the package content and source archive are checked for private keys,
token formats, credentials in URLs, and known private host values.
The check does not output found secrets. Automatic hits are evaluated:
public DynDNS provider URLs, RFC1918 network ranges, and loopback addresses
technically required. Historical mount names in the migration script serve
backup compatibility and contain no individual file contents or credentials.
Author attribution and license notices are expressly intended for publication.

English descriptions are created locally and verified; the manager does not use an external translation API during operation. Language catalogs contain exclusively program texts. Personal names, paths, and technical outputs are not sent to a translation service.

The old Git history is not retroactively cleaned up. For a new public repository,
use only the verified source archive. A local commit does not constitute release for uploading
the complete previous Git history.
Older packages remain unchanged and must be separately checked before distribution.

This is a source and artifact check, not a data privacy certification or
guarantee for later operation. Operators determine their own users, shares,
logging, and retention of their data.
Productive restores, hardware drivers, and all Windows configurations are not fully tested;
The Windows client and the Mint branch remain experimental.

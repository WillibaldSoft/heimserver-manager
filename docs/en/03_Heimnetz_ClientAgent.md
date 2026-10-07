# Manager Phase 3 - Home Network and Client Agent

## Goal

Setup of the Manager home network and client agent foundation.

## Functions

- Home network scan
- Adopt home network device as client
- Client agent table
- Token generation
- Installer as Hostname.sh
- Operating modes:
  - auto
  - connected
  - release-only
  - disabled
- Requirement notification to server control:
  - need-server
  - release-server

## Dependencies

- Server-Control Phase 2
- client_agents table
- home_clients table
- Server-Control Blocker API

## Security Goal

No private data in the code.
Tokens only in local database or client configuration file.

## Next Steps

1. Install the Phase 3 script.
2. Check /heimnetz.
3. Take over device from home network as client.
4. Download installer.
5. Install client.
6. Test need-server/release-server.

# CHANGELOG

Current version: **0.13-3** (Beta). Full changes are available in the
[English version history](Home_Server_Manager_Version_History.txt) and the
[German version history](../Heimserver_Manager_Versionsaenderungen.txt).

## Historical baseline

### Core
- Plugin Loader
- Module Overview
- Project Status Tools
- Migration Table

### Home Network
- IPv4/IPv6 Display
- Device Naming
- Device Types
- Offline Detection During Scan
- Soft Delete
- Adoption as Client Agent

### Client Agent
- Token-Based Agent
- Installer Download
- Set/Clear Requirement
- Server Control Blocker

### Server Control
- Blocker API
- Tvheadend Blocker
- Client Agent Blocker
- RTC Display

### TV / Tvheadend
- API Integration
- Streams
- Recordings
- Status Provider
- Blocker Provider
- RTC Recordings

### Sleep
- Sleep Engine
- Runtime
- Schedules
- Automatic Switches
- Dry Run / Actual Execution

## 0.13-3 – October 11, 2026 – Beta
- Linux client 0.4.36: readability preflight for HTTPS system and personal backups. List inaccessible paths, exclude them for this run only after explicit confirmation, and record exclusions in the inventory. New read errors during transfer still fail the backup. Local per-user exclusions remain supported; packages contain no private exclusions.
- Show incomplete incremental uploads and retire them after confirmation while preserving blocks and completed snapshots. Read files again and reuse identical blocks. Other devices, running verification, changed uploads and activity within ten minutes prevent retirement. Do not replace paused uploads.
- Background checksum verification with status polling and verification progress instead of one long HTTP request. Mark complete only after successful verification. A lost connection or service restart leaves completion unconfirmed; do not discard data prematurely.
- Personal inventory shows the home filesystem and excluded nested mounts. Clear read errors without an additional desktop crash report.
- Update manager and client together; manager changes require a checked restart. Run-scoped authentication requires the updated running manager. Package builds do not change running services or backups. Windows and simple folder/USB backup modes do not receive these Linux HTTPS extensions.

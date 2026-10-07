# Sleep & Wake: Check after neutral name migration

Checked on 24.09.2026, without real sleep/power-off, VM shutdown, or backup test run.

Corrected:
- Runtime and last security check receive the app context. Thus client agents are considered as in the web display.
- Time windows across midnight belong to the selected start weekday; RTC end times fall on the following day.
- Active app backup timers provide RTC candidates with two minutes lead time and a blocker shortly before the backup. DNS and update checks do not wake up the server constantly.
- The new backup RTC module is also included in the downloadable Server Manager package.

Validation: 8 new integration tests and 35 existing KVM tests successful. Live: five identical blockers in display and decision, including two client agents, two managed VMs, and one TV stream. RTC set for next Stirling backup; existing sleep schedules unchanged. No failed systemd services or module load errors. Sleep, photo lab, shares, TV, and presence pages respond successfully.

Limits: A physical power on/off or suspend/resume cycle was not executed. Likewise, not all write actions of all modules were performed. A successful HTTP call is not a complete functional test of the respective application.

Backup of previous files on the server: /var/backups/server-manager-sleep-20260924-000830

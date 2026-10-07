# Schlaf & Wake: Prüfung nach neutraler Namensmigration

Geprüft am 24.09.2026, ohne echten Schlaf-/Poweroff-, VM-Shutdown- oder Backup-Testlauf.

Korrigiert:
- Runtime und letzte Sicherheitsprüfung erhalten den App-Kontext. Damit werden Client-Agenten wie in der Webanzeige berücksichtigt.
- Zeitfenster über Mitternacht gehören zum ausgewählten Start-Wochentag; RTC-Endtermine liegen am Folgetag.
- Aktive App-Backup-Timer liefern RTC-Kandidaten mit zwei Minuten Vorlauf und einen Blocker kurz vor der Sicherung. DNS- und Updateprüfungen wecken den Server nicht ständig auf.
- Das neue Backup-RTC-Modul ist auch im herunterladbaren Server-Manager-Paket enthalten.

Prüfung: 8 neue Integrationstests und 35 vorhandene KVM-Tests erfolgreich. Live: fünf identische Blocker in Anzeige und Entscheidung, darunter zwei Client-Agenten, zwei verwaltete VMs und ein TV-Stream. RTC für nächste Stirling-Sicherung gesetzt; vorhandene Schlaf-Zeitpläne unverändert. Keine fehlgeschlagenen systemd-Dienste oder Modulladefehler. Schlaf-, Fotolabor-, Freigaben-, TV- und Presence-Seiten antworten erfolgreich.

Grenzen: Ein physischer Aus-/Ein- bzw. Suspend-/Resume-Zyklus wurde nicht ausgeführt. Ebenso wurden nicht sämtliche schreibenden Aktionen aller Module ausgeführt. Ein erfolgreicher HTTP-Aufruf ist kein vollständiger Funktionstest der jeweiligen Anwendung.

Sicherung der vorherigen Dateien auf dem Server: /var/backups/server-manager-sleep-20260924-000830

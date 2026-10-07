"""Display-only, browser-local language selection. English is the default for browser requests."""
import html
from flask import request, has_request_context
COOKIE = 'server_manager_language'
EN = {'Übersicht': 'Overview', 'Serverstatus': 'Server status', 'Web & Sicherheit': 'Web & Security', 'Schlaf & Wake': 'Sleep & Wake', 'Zeitpläne': 'Schedules', 'Schlafblocker': 'Sleep blockers', 'Virtuelle Maschinen': 'Virtual machines', 'Netzwerk': 'Network', 'Geräteübersicht': 'Devices', 'Client-Agenten': 'Client agents', 'Anwesenheit': 'Presence', 'Anwendungen': 'Applications', 'Meine Apps': 'My apps', 'Apps verwalten': 'Manage apps', 'TV & Aufnahmen': 'TV & recordings', 'Daten': 'Data', 'Speicher': 'Storage', 'Freigaben': 'Shares', 'Fotolabor': 'Photo lab', 'Einstellungen': 'Settings', 'Allgemein': 'General', 'Server & Modulpfade': 'Server & module paths', 'Zugang': 'Account', 'Module': 'Modules', 'Hauptbereiche': 'Main navigation', 'Unterseiten': 'Subpages', 'Sprache': 'Language', 'Speichern': 'Save', 'Benutzername': 'Username', 'Passwort': 'Password', 'Anmelden': 'Sign in', 'Abmelden': 'Sign out', 'Angemeldet: ': 'Signed in: ', 'Zugang ändern': 'Change account', 'Installationspasswort aktiv · ': 'Installation password active · ', 'Eigenes Passwort festlegen': 'Set your own password', 'Bitte anmelden, um den Server zu verwalten.': 'Please sign in to manage the server.', 'Formular abgelaufen. Bitte erneut anmelden.': 'Form expired. Please sign in again.', 'Zu viele Anmeldeversuche. Bitte in zehn Minuten erneut versuchen.': 'Too many sign-in attempts. Please try again in ten minutes.', 'Benutzername oder Passwort ist falsch.': 'Incorrect username or password.', 'Die Sprachwahl gilt für diesen Browser. Eigene Namen, Pfade und technische Protokolle bleiben unverändert.': 'The language applies to this browser. Custom names, paths and technical logs remain unchanged.'}

EN.update({'Alarme':'Alerts','Heimserver Manager':'Home Server Manager','Überblick':'Overview','Aufnahmen':'Recordings','Geplant':'Scheduled','Programm suchen':'Programme guide','Live-TV':'Live TV','Aufwachen':'Wake-up','Verbindung':'Connection','Scanner':'Scanner','Backup & Recovery':'Backup & recovery'})

def language():
    # Keep import-time source labels in German; choose presentation per request.
    if not has_request_context():return 'de'
    return 'de' if request.cookies.get(COOKIE) == 'de' else 'en'

def tr(text):
    from ui_translation import text as translate
    return EN.get(text, translate(text)) if language() == 'en' else translate(text)

def selector(csrf_input):
    # Only the current local path is reflected; query strings may contain secrets.
    dest = request.path
    return ("<form class='language-selector' method='post' action='/language' style='display:flex;gap:8px;align-items:center;margin:8px 0'>"
            + csrf_input + "<input type='hidden' name='next' value='" + html.escape(dest, quote=True)
            + "'><label>" + tr('Sprache') + " <select name='language'>"
            + ''.join("<option value='" + code + "'" + (' selected' if language() == code else '') + ">" + label + "</option>" for code,label in [('de','Deutsch'),('en','English')])
            + "</select></label><button type='submit'>" + tr('Speichern') + "</button></form>")

EN.update({
    "Automatische Updateprüfung": "Automatic update checks",
    "Vor der App-Updateprüfung werden die APT-Paketlisten einmal aktualisiert. Das gilt auch für „Alle Updates prüfen“. Es werden keine Pakete installiert. Bei einem APT-Fehler wird die App-Prüfung abgebrochen und das Protokoll verlinkt.": "APT package lists are refreshed once before checking app updates, including Check all updates. No packages are installed. If APT fails, app checks stop and a log link is provided.",
})

EN.update({"Menü & Konto":"Menu & account","Zum Inhalt":"Skip to content","Tabelle – bei Bedarf horizontal scrollen":"Table – scroll horizontally if needed"})

EN.update({'Anmeldedauer': 'Session duration', 'Dauer in Minuten (1–1440; 60 Minuten = 1 Stunde)': 'Duration in minutes (1–1440; 60 minutes = 1 hour)', 'Aktuelles Passwort': 'Current password', 'Anmeldedauer speichern': 'Save session duration', 'Anmeldedauer: 1 bis 1440 Minuten eingeben.': 'Session duration: enter 1 to 1440 minutes.', 'Anmeldedauer gespeichert. Gilt ab der nächsten Anmeldung; laufende Sitzungen behalten ihr Ablaufdatum.': 'Session duration saved. Applies from the next sign-in; existing sessions keep their expiry time.', 'Feste Dauer ab Anmeldung, unabhängig von Aktivität. Danach erneut mit demselben Passwort anmelden. Laufende Hintergrundaufträge laufen weiter.': 'Fixed duration from sign-in, regardless of activity. Sign in again with the same password afterwards. Running background jobs continue.'})

EN.update({"Freigaben & Benutzer": "Shares & users"})

EN.update({"Reparaturskripte":"Repair scripts"})

EN.update({"Manager aktualisieren":"Update Manager"})

EN.update({"Standard-Anmeldedaten": "Default sign-in details", "Bitte nach der ersten Anmeldung unter „Zugang ändern“ ein eigenes Passwort festlegen.": "After your first sign-in, set your own password under “Change account”."})

EN.update({'Modulauswahl':'Module selection','Moduldiagnose':'Module diagnostics'})

EN.update({"Betrieb, Speicher, Schlaf- und Weckzeiten und Schlafblocker.":"Operation, storage, sleep and wake schedules and sleep blockers.","Geräte im Heimnetz, Client-Agenten und Anwesenheit.":"Home network devices, client agents and presence.","Hostnamen, Anbieter und automatische IP-Aktualisierungen verwalten.":"Manage hostnames, providers and automatic IP updates.","Virtuelle Maschinen verwalten, sichern und wiederherstellen.":"Manage, back up and restore virtual machines."})

EN.update({"Scanner API für Home Assistant":"Scanner API for Home Assistant"})

EN.update({"Programme installieren und deinstallieren, Updates durchführen sowie Backups erstellen und wiederherstellen.": "Install and uninstall applications, run updates, and create and restore backups."})

EN.update({'Sprachen':'Languages', 'Englisch ist die Standardsprache. Die Auswahl gilt für diesen Browser.':'English is the default language. Your selection applies to this browser.'})

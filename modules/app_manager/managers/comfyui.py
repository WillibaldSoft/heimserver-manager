from server_settings import app_literal as host_literal
# -*- coding: utf-8 -*-
from pathlib import Path
import time

from .base import BaseManager
from ..runner import sh
from ..update_engine import run_update_backup_check

class Manager(BaseManager):
    app_id = 'comfyui'
    label = 'ComfyUI'
    kind = 'native/python'
    service = 'comfyui.service'
    web_url = 'http://127.0.0.1:8188'

    def update_check(self):
        """
        Prüft ComfyUI getrennt nach Stable-Release und Development.

        Ein normal verfügbares Update bedeutet ausschließlich:
        neuer offizieller Stable-Tag.

        Neuere Commits auf origin/master werden separat als
        Development-Stand gemeldet und lösen kein normales Update aus.
        """

        repo = host_literal('comfyui', "/opt/comfyui/ComfyUI")

        def git(args, timeout=30):
            command = (
                host_literal('comfyui', "sudo -n -u comfyui "
                "git -C {} {}").format(
                    repr(repo),
                    args,
                )
            )
            return sh(command, timeout=timeout)

        # Repository vorhanden?
        git_dir = Path(repo) / ".git"

        if not git_dir.exists():
            return {
                "supported": True,
                "ok": False,
                "state": "unknown",
                "label": "Unbekannt",
                "message": (
                    "Kein ComfyUI Git-Repository erkannt."
                ),
                "app_id": self.app_id,
                "app_label": self.label,
                "kind": self.kind,
                "current_version": None,
                "latest_version": None,
                "update_available": None,
                "safe_to_update": False,
                "requires_backup": True,
                "method": "comfyui-stable-git",
                "details": {
                    "repo": repo,
                },
                "warnings": [],
            }

        # Remote aktualisieren, inklusive Tags.
        fetch_r = git(
            "fetch --prune --tags origin",
            timeout=120,
        )

        if not fetch_r.get("ok"):
            return {
                "supported": True,
                "ok": False,
                "state": "unknown",
                "label": "Unbekannt",
                "message": (
                    "ComfyUI Git-Remote konnte nicht "
                    "aktualisiert werden."
                ),
                "app_id": self.app_id,
                "app_label": self.label,
                "kind": self.kind,
                "current_version": None,
                "latest_version": None,
                "update_available": None,
                "safe_to_update": False,
                "requires_backup": True,
                "method": "comfyui-stable-git",
                "details": {
                    "repo": repo,
                    "fetch_returncode": fetch_r.get("returncode"),
                    "fetch_stderr": fetch_r.get("stderr") or "",
                },
                "warnings": [
                    "Stable-Release konnte nicht zuverlässig geprüft werden."
                ],
            }

        def stdout(args, timeout=30):
            r = git(args, timeout=timeout)
            return (
                (r.get("stdout") or "").strip(),
                r,
            )

        head, head_r = stdout("rev-parse HEAD")
        head_short, _ = stdout("rev-parse --short HEAD")
        branch, _ = stdout("branch --show-current")
        dirty_text, _ = stdout("status --porcelain")

        master, master_r = stdout(
            "rev-parse origin/master"
        )
        master_short, _ = stdout(
            "rev-parse --short origin/master"
        )

        # Neuester offizieller Versions-Tag.
        stable_tag, stable_tag_r = stdout(
            "tag "
            "--list 'v[0-9]*' "
            "--sort=-version:refname "
            "| head -1"
        )

        if not stable_tag:
            return {
                "supported": True,
                "ok": False,
                "state": "unknown",
                "label": "Unbekannt",
                "message": (
                    "Kein offizieller ComfyUI Stable-Tag gefunden."
                ),
                "app_id": self.app_id,
                "app_label": self.label,
                "kind": self.kind,
                "current_version": head_short or None,
                "latest_version": None,
                "update_available": None,
                "safe_to_update": False,
                "requires_backup": True,
                "method": "comfyui-stable-git",
                "details": {
                    "repo": repo,
                    "branch": branch,
                    "local_revision": head,
                    "upstream_revision": master,
                },
                "warnings": [
                    "Stable-Release konnte nicht bestimmt werden."
                ],
            }

        stable_commit, _ = stdout(
            "rev-list -n1 {}".format(stable_tag)
        )

        stable_short, _ = stdout(
            "rev-parse --short {}".format(stable_tag)
        )

        describe, _ = stdout(
            "describe --tags --long --always HEAD"
        )

        exact_tag, _ = stdout(
            "describe --tags --exact-match HEAD 2>/dev/null || true"
        )

        development_installed = not bool(
            exact_tag
        )

        installed_channel = (
            "development"
            if development_installed
            else "stable"
        )

        # Development-Differenz HEAD <-> origin/master.
        behind_s, _ = stdout(
            "rev-list --count HEAD..origin/master"
        )
        ahead_s, _ = stdout(
            "rev-list --count origin/master..HEAD"
        )

        try:
            behind = int(behind_s or 0)
        except Exception:
            behind = 0

        try:
            master_divergent_commits = int(ahead_s or 0)
        except Exception:
            master_divergent_commits = 0

        dirty = bool(dirty_text.strip())

        # Offizielle Stable-Commits koennen auf origin/release/* liegen
        # und deshalb von origin/master abweichen, ohne lokale Commits
        # des Benutzers zu sein.
        release_contains_s, _ = stdout(
            "branch -r --contains HEAD"
        )

        release_branches = [
            line.strip()
            for line in (release_contains_s or "").splitlines()
            if line.strip().startswith("origin/release/")
        ]

        official_release_checkout = bool(release_branches)

        ahead = (
            0
            if official_release_checkout
            else master_divergent_commits
        )

        # Beziehung HEAD -> Stable.
        head_is_stable = (
            bool(head)
            and bool(stable_commit)
            and head == stable_commit
        )

        ancestor_r = git(
            "merge-base --is-ancestor HEAD {}".format(
                stable_tag
            )
        )

        stable_fast_forward = (
            ancestor_r.get("returncode") == 0
        )

        stable_update_available = not head_is_stable

        development_commits = behind

        development_available = (
            development_commits > 0
        )

        # Automatisch auf Stable nur bei sauberem,
        # reinem Fast-Forward.
        safe_to_update = bool(
            stable_update_available
            and stable_fast_forward
            and not dirty
            and ahead == 0
        )

        warnings = []

        if dirty:
            warnings.append(
                "Lokale Änderungen im ComfyUI-Repository vorhanden."
            )

        if ahead > 0:
            warnings.append(
                "{} lokale Commit(s) sind origin/master voraus.".format(
                    ahead
                )
            )

        if (
            stable_update_available
            and not stable_fast_forward
        ):
            warnings.append(
                "Der aktuelle Checkout kann nicht per Fast-Forward "
                "auf den Stable-Release wechseln."
            )

        if stable_update_available:
            state = "available"
            label = "Stable-Update verfügbar"

            if stable_fast_forward:
                message = (
                    "ComfyUI Stable {} ist verfügbar.".format(
                        stable_tag
                    )
                )
            else:
                message = (
                    "ComfyUI Stable {} ist verfügbar, der aktuelle "
                    "Checkout divergiert jedoch vom Stable-Zweig.".format(
                        stable_tag
                    )
                )

        else:
            state = "current"
            label = "Aktuell (Stable)"

            if development_available:
                message = (
                    "ComfyUI {} ist installiert; {} neuere "
                    "Development-Commit(s) sind verfügbar.".format(
                        stable_tag,
                        development_commits,
                    )
                )
            else:
                message = (
                    "ComfyUI {} ist aktuell.".format(
                        stable_tag
                    )
                )

        return {
            "supported": True,
            "ok": True,
            "state": state,
            "label": label,
            "message": message,
            "app_id": self.app_id,
            "app_label": self.label,
            "kind": self.kind,
            "method": "comfyui-stable-git",

            # Generische Update-Engine:
            # update_available bedeutet NUR Stable.
            "current_version": (
                "{} / {}".format(
                    describe or "unbekannt",
                    head_short or "unbekannt",
                )
            ),
            "latest_version": (
                "{} / {}".format(
                    stable_tag,
                    stable_short or "unbekannt",
                )
            ),
            "update_available": stable_update_available,
            "safe_to_update": safe_to_update,
            "requires_backup": True,

            # ComfyUI-spezifische strukturierte Daten.
            "stable_update_available": stable_update_available,
            "stable_version": stable_tag,
            "stable_revision": stable_commit,
            "stable_revision_short": stable_short,

            "development_available": development_available,
            "development_version": master_short,
            "development_revision": master,
            "development_commits": development_commits,

            "installed_channel": installed_channel,
            "development_installed": development_installed,
            "installed_release_tag": exact_tag or None,

            "details": {
                "repo": repo,
                "branch": branch,
                "local_revision": head,
                "local_revision_short": head_short,
                "local_describe": describe,
                "exact_tag": exact_tag or None,
                "installed_channel": installed_channel,
                "development_installed": development_installed,
                "stable_tag": stable_tag,
                "stable_revision": stable_commit,
                "stable_revision_short": stable_short,
                "development_revision": master,
                "development_revision_short": master_short,
                "development_commits": development_commits,
                "ahead": ahead,
                "behind": behind,
                "dirty": dirty,
                "dirty_files": dirty_text,
                "stable_fast_forward": stable_fast_forward,
                "head_is_stable": head_is_stable,
            },

            "warnings": warnings,
        }


    def update_plan(self):
        """Liefert den nativen Git-Updateplan für ComfyUI."""

        check = self.update_check()

        details = check.get("details") or {}

        dirty = bool(
            details.get("dirty")
        )

        ahead = int(
            details.get("ahead") or 0
        )

        stable_update_available = bool(
            check.get("stable_update_available")
        )

        stable_fast_forward = bool(
            details.get("stable_fast_forward")
        )

        stable_switch_required = bool(
            stable_update_available
            and not stable_fast_forward
        )

        blocked = bool(
            dirty
            or ahead > 0
            or stable_switch_required
        )

        if dirty:
            guard_reason = "local_changes"
            guard_message = (
                "Lokale Änderungen im ComfyUI-Repository vorhanden."
            )
            recommendation = (
                "Lokale Änderungen vor dem Update prüfen und "
                "bereinigen oder sichern."
            )

        elif ahead > 0:
            guard_reason = "local_commits"
            guard_message = (
                "Lokale ComfyUI-Commits sind dem Upstream voraus."
            )
            recommendation = (
                "Lokale Commits vor dem automatischen Update "
                "manuell prüfen."
            )

        elif stable_switch_required:
            guard_reason = "stable_switch_required"
            guard_message = (
                "Der installierte ComfyUI-Stand liegt auf einer "
                "anderen Git-Linie als der aktuelle Stable-Release."
            )
            recommendation = (
                "Für den Wechsel auf Stable den separaten "
                "Stable-Wechsel verwenden."
            )

        else:
            guard_reason = None
            guard_message = ""
            recommendation = ""

        return {
            "supported": True,
            "ok": bool(check.get("ok", True)),
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "method": "comfyui-git",
            "update_available": check.get("update_available"),
            "state": check.get("state"),
            "current_version": check.get("current_version"),
            "latest_version": check.get("latest_version"),
            "stable_version": check.get("stable_version"),
            "stable_revision": check.get("stable_revision"),
            "stable_revision_short": check.get(
                "stable_revision_short"
            ),
            "stable_update_available": check.get(
                "stable_update_available"
            ),
            "development_revision": check.get(
                "development_revision"
            ),
            "development_version": check.get(
                "development_version"
            ),
            "development_commits": check.get(
                "development_commits"
            ),
            "requires_backup": True,
            "safe_to_update": bool(
                check.get("safe_to_update")
                and not blocked
            ),
            "update_guard": {
                "blocked": blocked,
                "reason": guard_reason,
                "severity": "error" if blocked else "info",
                "message": guard_message,
                "details": check.get("warnings") or [],
                "recommendation": recommendation,
            },
            "warnings": check.get("warnings") or [],
            "steps": [
                {
                    "id": "git_precheck",
                    "label": "ComfyUI Git-Repository prüfen",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "git_update",
                    "label": "ComfyUI Repository aktualisieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "torch_dependencies",
                    "label": "PyTorch/CUDA-Stack beibehalten",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "python_dependencies",
                    "label": "Python-Abhängigkeiten aktualisieren",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "python_sanity_check",
                    "label": "Python-/CUDA-Umgebung prüfen",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "service_restart",
                    "label": "ComfyUI-Dienst neu starten",
                    "required": True,
                    "automatic": True,
                },
                {
                    "id": "service_verify",
                    "label": "ComfyUI-Dienst und WebUI prüfen",
                    "required": True,
                    "automatic": True,
                },
            ],
        }


    def stable_switch_plan(self):
        """
        Plant einen kontrollierten Wechsel vom aktuellen
        ComfyUI-Git-Stand auf den neuesten Stable-Release.

        Dieser Pfad ist bewusst vom normalen Fast-Forward-Update
        getrennt. Er darf auch bei divergierenden Git-Linien
        verwendet werden, solange das Repository sauber ist und
        keine lokalen Commits gegenüber origin/master vorliegen.
        """

        check = self.update_check()
        details = check.get("details") or {}

        repo = details.get(
            "repo",
            host_literal('comfyui', "/opt/comfyui/ComfyUI"),
        )

        current_revision = str(
            details.get("local_revision") or ""
        ).strip()

        current_revision_short = str(
            details.get("local_revision_short") or ""
        ).strip()

        current_branch = str(
            details.get("branch") or ""
        ).strip()

        stable_revision = str(
            check.get("stable_revision")
            or details.get("stable_revision")
            or ""
        ).strip()

        stable_revision_short = str(
            check.get("stable_revision_short")
            or details.get("stable_revision_short")
            or ""
        ).strip()

        stable_version = str(
            check.get("stable_version")
            or details.get("stable_tag")
            or ""
        ).strip()

        dirty = bool(details.get("dirty"))
        ahead = int(details.get("ahead") or 0)

        already_stable = bool(
            current_revision
            and stable_revision
            and current_revision == stable_revision
        )

        errors = []

        if not current_revision:
            errors.append(
                "Aktueller ComfyUI Git-Commit konnte nicht bestimmt werden."
            )

        if not stable_revision:
            errors.append(
                "Stable-Commit konnte nicht bestimmt werden."
            )

        if not stable_version:
            errors.append(
                "Stable-Release-Tag konnte nicht bestimmt werden."
            )

        if dirty:
            errors.append(
                "Lokale Änderungen im ComfyUI-Repository vorhanden."
            )

        # Sobald HEAD exakt dem Stable-Release entspricht, ist die
        # Abweichung gegenüber origin/master kein Fehler mehr.
        # Der lokale Branch "stable" ist absichtlich nicht mit
        # origin/master identisch.
        if ahead > 0 and not already_stable:
            errors.append(
                "Lokale ComfyUI-Commits gegenüber origin/master vorhanden."
            )

        safe = bool(
            not already_stable
            and not errors
        )

        return {
            "supported": True,
            "ok": bool(already_stable or safe),
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "method": "comfyui-stable-switch",
            "safe_to_switch": safe,
            "requires_backup": True,
            "repo": repo,
            "current_revision": current_revision,
            "current_revision_short": current_revision_short,
            "current_branch": current_branch,
            "stable_version": stable_version,
            "stable_revision": stable_revision,
            "stable_revision_short": stable_revision_short,
            "already_stable": already_stable,
            "dirty": dirty,
            "ahead": ahead,
            "errors": errors,
            "message": (
                "ComfyUI befindet sich bereits exakt auf dem Stable-Release."
                if already_stable
                else (
                    "Kontrollierter Wechsel auf ComfyUI Stable ist möglich."
                    if safe
                    else
                    "Wechsel auf ComfyUI Stable ist derzeit blockiert."
                )
            ),
            "steps": [
                {
                    "id": "backup",
                    "label": "Aktuellen ComfyUI-Zustand sichern",
                    "required": True,
                },
                {
                    "id": "save_revision",
                    "label": "Aktuellen Git-Commit als Rollback-Ziel speichern",
                    "required": True,
                },
                {
                    "id": "service_stop",
                    "label": "ComfyUI-Dienst stoppen",
                    "required": True,
                },
                {
                    "id": "stable_checkout",
                    "label": (
                        "Auf Stable {} wechseln".format(
                            stable_version or "Release"
                        )
                    ),
                    "required": True,
                },
                {
                    "id": "dependencies",
                    "label": "Python-/CUDA-Abhängigkeiten abgleichen",
                    "required": True,
                },
                {
                    "id": "sanity_check",
                    "label": "Python-/CUDA-Umgebung prüfen",
                    "required": True,
                },
                {
                    "id": "service_start",
                    "label": "ComfyUI-Dienst starten",
                    "required": True,
                },
                {
                    "id": "verify",
                    "label": "Stable-Version und WebUI verifizieren",
                    "required": True,
                },
                {
                    "id": "rollback",
                    "label": (
                        "Bei Fehler auf {} zurückkehren".format(
                            current_revision_short or "alten Commit"
                        )
                    ),
                    "required": True,
                    "conditional": True,
                },
            ],
        }


    def _stable_switch_rollback_context(
        self,
        backup_check,
        expected_revision=None,
        expected_branch=None,
    ):
        """
        Lädt den autoritativen Rollback-Zustand ausschließlich
        aus dem validierten Pre-Update-Backup.

        Verwendet:
          - extra/git-head.txt
          - extra/git-branch.txt
          - extra/pip-freeze.txt
        """

        result = {
            "ok": False,
            "backup_run_id": None,
            "backup_work_dir": None,
            "revision": None,
            "branch": None,
            "pip_freeze": None,
            "errors": [],
        }

        if (
            not isinstance(backup_check, dict)
            or backup_check.get("ok") is not True
        ):
            result["errors"].append(
                "Pre-Update-Backup ist nicht validiert."
            )
            return result

        prepared = backup_check.get("backup") or {}

        result["backup_run_id"] = prepared.get(
            "run_id"
        )

        backup = prepared.get("backup") or {}

        work_dir = str(
            backup.get("work_dir") or ""
        ).strip()

        if not work_dir:
            result["errors"].append(
                "Backup-Arbeitsverzeichnis fehlt."
            )
            return result

        work = Path(work_dir)

        if not work.is_dir():
            result["errors"].append(
                "Backup-Arbeitsverzeichnis existiert nicht."
            )
            return result

        result["backup_work_dir"] = str(work)

        extra = work / "extra"

        git_head_file = extra / "git-head.txt"
        git_branch_file = extra / "git-branch.txt"
        pip_freeze_file = extra / "pip-freeze.txt"

        for required in (
            git_head_file,
            git_branch_file,
            pip_freeze_file,
        ):
            if not required.is_file():
                result["errors"].append(
                    "Rollback-Datei fehlt: {}".format(
                        required
                    )
                )

        if result["errors"]:
            return result

        revision = git_head_file.read_text(
            encoding="utf-8"
        ).strip()

        branch_raw = git_branch_file.read_text(
            encoding="utf-8"
        ).strip()

        # Aktuelle Backups enthalten z.B.
        #   ## master...origin/master [hinterher 7]
        branch = ""

        if branch_raw.startswith("## "):
            branch = branch_raw[3:].split(
                "...",
                1,
            )[0].split()[0].strip()

        if not branch:
            branch = str(
                expected_branch or ""
            ).strip()

        expected_revision = str(
            expected_revision or ""
        ).strip()

        if (
            expected_revision
            and revision != expected_revision
        ):
            result["errors"].append(
                "Backup-Git-HEAD stimmt nicht mit dem "
                "aktuellen geplanten Ausgangsstand überein."
            )

        if not revision:
            result["errors"].append(
                "Backup enthält keinen Git-HEAD."
            )

        if not branch:
            result["errors"].append(
                "Rollback-Branch konnte nicht bestimmt werden."
            )

        if pip_freeze_file.stat().st_size <= 0:
            result["errors"].append(
                "pip-freeze.txt ist leer."
            )

        if result["errors"]:
            return result

        result.update({
            "ok": True,
            "revision": revision,
            "branch": branch,
            "pip_freeze": str(pip_freeze_file),
        })

        return result


    def stable_switch_execute(self, session=None):
        """
        Kontrollierter Wechsel auf den neuesten Stable-Release.

        Aktuell absichtlich nur als Simulation freigegeben.
        Die spätere echte Ausführung verwendet denselben Plan und
        erhält zusätzlich Pre-Update-Backup sowie automatischen
        Git-/Dependency-Rollback.

        PyTorch/CUDA wird beim Stable-Wechsel bewusst nicht geändert.
        Der bereits funktionierende GPU-Stack bleibt erhalten.
        """

        session = (
            session
            if isinstance(session, dict)
            else {}
        )

        simulate = bool(
            session.get("simulate", True)
        )

        plan = self.stable_switch_plan()

        if not plan.get("safe_to_switch"):
            return {
                "supported": True,
                "ok": False,
                "blocked": True,
                "simulate": simulate,
                "mode": (
                    "simulation"
                    if simulate
                    else "execute"
                ),
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": (
                    "ComfyUI Stable-Wechsel ist blockiert."
                ),
                "plan": plan,
                "errors": plan.get("errors") or [],
                "steps": [],
            }

        repo = str(
            plan.get("repo")
            or host_literal('comfyui', "/opt/comfyui/ComfyUI")
        )

        current_revision = str(
            plan.get("current_revision") or ""
        ).strip()

        current_branch = str(
            plan.get("current_branch") or ""
        ).strip()

        stable_revision = str(
            plan.get("stable_revision") or ""
        ).strip()

        stable_version = str(
            plan.get("stable_version") or ""
        ).strip()

        python = repo + "/venv/bin/python"
        requirements = repo + "/requirements.txt"

        commands = {
            "service_stop": (
                "sudo -n systemctl stop comfyui.service"
            ),

            "stable_checkout": (
                host_literal('comfyui', "sudo -n -u comfyui "
                "git -C {} switch -C stable {}").format(
                    repr(repo),
                    repr(stable_revision),
                )
            ),

            # Kein Torch-Upgrade.
            #
            # Bereits installiertes torch/torchvision/torchaudio
            # erfüllen die ungepinnten Requirements und bleiben
            # deshalb erhalten.
            "dependencies": (
                host_literal('comfyui', "sudo -n -u comfyui "
                "{} -m pip install -r {}").format(
                    python,
                    repr(requirements),
                )
            ),

            "sanity_check": (
                host_literal('comfyui', "sudo -n -u comfyui "
                "{} -c {}").format(
                    python,
                    repr(
                        "import torch; "
                        "from importlib.metadata import version; "
                        "import comfy_kitchen; "
                        "from comfy_kitchen.backends.eager import na; "
                        "assert torch.cuda.is_available(), "
                        "'CUDA ist nicht verfügbar'; "
                        "print('torch=' + str(torch.__version__)); "
                        "print('cuda=' + str(torch.version.cuda)); "
                        "print('gpu=' + str(torch.cuda.get_device_name(0))); "
                        "print('comfy_kitchen=' + "
                        "version('comfy-kitchen')); "
                        "print('comfy_kitchen_eager_na=ok')"
                    ),
                )
            ),

            "service_start": (
                "sudo -n systemctl start comfyui.service"
            ),

            "rollback_checkout": (
                (
                    host_literal('comfyui', "sudo -n -u comfyui "
                    "git -C {} switch {}")
                ).format(
                    repr(repo),
                    repr(current_branch),
                )
                if current_branch
                else (
                    host_literal('comfyui', "sudo -n -u comfyui "
                    "git -C {} switch --detach {}")
                ).format(
                    repr(repo),
                    repr(current_revision),
                )
            ),

            "rollback_dependencies": (
                host_literal('comfyui', "sudo -n -u comfyui "
                "{} -m pip install -r {}").format(
                    python,
                    repr(requirements),
                )
            ),

            "rollback_start": (
                "sudo -n systemctl restart comfyui.service"
            ),
        }

        if not simulate:
            authorized = bool(
                session.get("stable_switch_authorized")
            )

            # Echtlauf nur mit explizit gebundenem und durch die
            # zentrale Update-Engine validiertem Prepare-Run.
            backup_check = run_update_backup_check(
                self,
                session=session,
            )

            backup_ok = bool(
                isinstance(backup_check, dict)
                and backup_check.get("ok") is True
            )

            if not authorized or not backup_ok:
                errors = []

                if not authorized:
                    errors.append(
                        "Stable-Wechsel wurde nicht ausdrücklich autorisiert."
                    )

                if not backup_ok:
                    backup_errors = (
                        backup_check.get("errors") or []
                        if isinstance(backup_check, dict)
                        else []
                    )

                    if backup_errors:
                        errors.extend(
                            "Pre-Update-Backup: {}".format(error)
                            for error in backup_errors
                        )
                    else:
                        errors.append(
                            "Kein gültiges gebundenes "
                            "Pre-Update-Backup vorhanden."
                        )

                return {
                    "supported": True,
                    "ok": False,
                    "blocked": True,
                    "simulate": False,
                    "mode": "execute",
                    "app_id": self.app_id,
                    "label": self.label,
                    "kind": self.kind,
                    "message": (
                        "Echter ComfyUI Stable-Wechsel ist "
                        "durch Sicherheitsprüfung blockiert."
                    ),
                    "plan": plan,
                    "commands": commands,
                    "errors": errors,
                    "backup_check": backup_check,
                    "steps": [],
                }

            rollback_context = (
                self._stable_switch_rollback_context(
                    backup_check,
                    expected_revision=current_revision,
                    expected_branch=current_branch,
                )
            )

            if not rollback_context.get("ok"):
                return {
                    "supported": True,
                    "ok": False,
                    "blocked": True,
                    "simulate": False,
                    "mode": "execute",
                    "app_id": self.app_id,
                    "label": self.label,
                    "kind": self.kind,
                    "message": (
                        "Rollback-Daten des gebundenen "
                        "Pre-Update-Backups sind ungültig."
                    ),
                    "plan": plan,
                    "backup_check": backup_check,
                    "rollback_context": rollback_context,
                    "errors": (
                        rollback_context.get("errors") or []
                    ),
                    "steps": [],
                }

            rollback_revision = str(
                rollback_context.get("revision") or ""
            ).strip()

            rollback_branch = str(
                rollback_context.get("branch") or ""
            ).strip()

            rollback_pip_freeze = str(
                rollback_context.get("pip_freeze") or ""
            ).strip()

            # Ab hier stammen Rollback-Commit und Python-Paketstand
            # ausschließlich aus dem validierten Backup.
            commands["rollback_checkout"] = (
                host_literal('comfyui', "sudo -n -u comfyui "
                "git -C {} switch {} && "
                "sudo -n -u comfyui "
                "git -C {} reset --hard {}").format(
                    repr(repo),
                    repr(rollback_branch),
                    repr(repo),
                    repr(rollback_revision),
                )
            )

            commands["rollback_dependencies"] = (
                host_literal('comfyui', "sudo -n -u comfyui "
                "{} -m pip install -r {}").format(
                    python,
                    repr(rollback_pip_freeze),
                )
            )

            steps = []

            def add_step(
                order,
                step_id,
                label,
                status,
                changed=False,
                message="",
                command="",
                output="",
                returncode=None,
            ):
                steps.append({
                    "order": order,
                    "id": step_id,
                    "label": label,
                    "status": status,
                    "changed": bool(changed),
                    "message": message,
                    "command": command,
                    "output": output,
                    "returncode": returncode,
                })

            def run_command(
                order,
                step_id,
                label,
                command,
                changed=True,
                timeout=600,
            ):
                r = sh(
                    command,
                    timeout=timeout,
                )

                output = (
                    (r.get("stdout") or "")
                    + "\n"
                    + (r.get("stderr") or "")
                ).strip()

                ok = bool(r.get("ok"))

                add_step(
                    order,
                    step_id,
                    label,
                    "executed" if ok else "failed",
                    changed if ok else False,
                    "OK" if ok else "Fehlgeschlagen",
                    command,
                    output,
                    r.get("returncode"),
                )

                return ok

            def rollback(reason):
                rollback_steps = []

                def rb(
                    step_id,
                    label,
                    command,
                    timeout=600,
                ):
                    r = sh(
                        command,
                        timeout=timeout,
                    )

                    output = (
                        (r.get("stdout") or "")
                        + "\n"
                        + (r.get("stderr") or "")
                    ).strip()

                    item = {
                        "id": step_id,
                        "label": label,
                        "ok": bool(r.get("ok")),
                        "command": command,
                        "output": output,
                        "returncode": r.get("returncode"),
                    }

                    rollback_steps.append(item)

                    return item["ok"]

                checkout_ok = rb(
                    "rollback_checkout",
                    "Auf vorherigen Git-Stand zurückkehren",
                    commands["rollback_checkout"],
                )

                deps_ok = False

                if checkout_ok:
                    deps_ok = rb(
                        "rollback_dependencies",
                        "Vorherige ComfyUI-Abhängigkeiten wiederherstellen",
                        commands["rollback_dependencies"],
                        timeout=1800,
                    )

                restart_ok = rb(
                    "rollback_restart",
                    "ComfyUI nach Rollback neu starten",
                    commands["rollback_start"],
                    timeout=120,
                )

                try:
                    health = self.health()
                except Exception as e:
                    health = {
                        "ok": False,
                        "error": str(e),
                    }

                rollback_ok = bool(
                    checkout_ok
                    and deps_ok
                    and restart_ok
                    and isinstance(health, dict)
                    and health.get("ok") is True
                )

                return {
                    "ok": rollback_ok,
                    "reason": reason,
                    "target_branch": rollback_branch,
                    "target_revision": rollback_revision,
                    "pip_freeze": rollback_pip_freeze,
                    "steps": rollback_steps,
                    "health": health,
                }

            # ------------------------------------------------
            # 1. Dienst stoppen
            # ------------------------------------------------

            if not run_command(
                1,
                "service_stop",
                "ComfyUI-Dienst stoppen",
                commands["service_stop"],
                changed=True,
                timeout=120,
            ):
                return {
                    "supported": True,
                    "ok": False,
                    "blocked": False,
                    "mode": "execute",
                    "app_id": self.app_id,
                    "message": (
                        "ComfyUI-Dienst konnte nicht gestoppt werden."
                    ),
                    "steps": steps,
                    "rollback": None,
                }

            # ------------------------------------------------
            # 2. Stable-Checkout
            # ------------------------------------------------

            if not run_command(
                2,
                "stable_checkout",
                "Auf Stable {} wechseln".format(
                    stable_version
                ),
                commands["stable_checkout"],
                changed=True,
            ):
                rb = rollback(
                    "Stable-Checkout fehlgeschlagen."
                )

                return {
                    "supported": True,
                    "ok": False,
                    "mode": "execute",
                    "app_id": self.app_id,
                    "message": (
                        "Stable-Checkout fehlgeschlagen; "
                        "Rollback wurde ausgeführt."
                    ),
                    "steps": steps,
                    "rollback": rb,
                }

            # ------------------------------------------------
            # 3. Requirements
            # ------------------------------------------------

            if not run_command(
                3,
                "dependencies",
                "ComfyUI-Abhängigkeiten abgleichen",
                commands["dependencies"],
                changed=True,
                timeout=1800,
            ):
                rb = rollback(
                    "Dependency-Aktualisierung fehlgeschlagen."
                )

                return {
                    "supported": True,
                    "ok": False,
                    "mode": "execute",
                    "app_id": self.app_id,
                    "message": (
                        "Dependencies fehlgeschlagen; "
                        "Rollback wurde ausgeführt."
                    ),
                    "steps": steps,
                    "rollback": rb,
                }

            # ------------------------------------------------
            # 4. Sanity
            # ------------------------------------------------

            if not run_command(
                4,
                "sanity_check",
                "Python-/CUDA-Umgebung prüfen",
                commands["sanity_check"],
                changed=False,
                timeout=120,
            ):
                rb = rollback(
                    "Python-/CUDA-Sanity-Check fehlgeschlagen."
                )

                return {
                    "supported": True,
                    "ok": False,
                    "mode": "execute",
                    "app_id": self.app_id,
                    "message": (
                        "Sanity-Check fehlgeschlagen; "
                        "Rollback wurde ausgeführt."
                    ),
                    "steps": steps,
                    "rollback": rb,
                }

            # ------------------------------------------------
            # 5. Start
            # ------------------------------------------------

            if not run_command(
                5,
                "service_start",
                "ComfyUI-Dienst starten",
                commands["service_start"],
                changed=True,
                timeout=120,
            ):
                rb = rollback(
                    "ComfyUI-Dienststart fehlgeschlagen."
                )

                return {
                    "supported": True,
                    "ok": False,
                    "mode": "execute",
                    "app_id": self.app_id,
                    "message": (
                        "Dienststart fehlgeschlagen; "
                        "Rollback wurde ausgeführt."
                    ),
                    "steps": steps,
                    "rollback": rb,
                }

            # ------------------------------------------------
            # 6. Verify
            # ------------------------------------------------

            verify = self.update_verify()

            add_step(
                6,
                "verify",
                "Stable-Version und WebUI verifizieren",
                "executed" if verify.get("ok") else "failed",
                False,
                verify.get("message") or "",
                "",
                "",
                0 if verify.get("ok") else 1,
            )

            if not verify.get("ok"):
                rb = rollback(
                    "Stable-Verifikation fehlgeschlagen."
                )

                return {
                    "supported": True,
                    "ok": False,
                    "mode": "execute",
                    "app_id": self.app_id,
                    "message": (
                        "Stable-Verifikation fehlgeschlagen; "
                        "Rollback wurde ausgeführt."
                    ),
                    "steps": steps,
                    "verify": verify,
                    "rollback": rb,
                }

            return {
                "supported": True,
                "ok": True,
                "blocked": False,
                "simulate": False,
                "mode": "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "current_revision": current_revision,
                "previous_branch": current_branch,
                "stable_version": stable_version,
                "stable_revision": stable_revision,
                "message": (
                    "ComfyUI wurde erfolgreich auf Stable {} "
                    "umgestellt.".format(stable_version)
                ),
                "torch_policy": {
                    "change_torch": False,
                },
                "backup_check": backup_check,
                "rollback_context": rollback_context,
                "steps": steps,
                "verify": verify,
                "rollback": None,
            }

        steps = [
            {
                "order": 1,
                "id": "pre_update_backup",
                "label": "Pre-Update-Backup prüfen",
                "status": "simulated",
                "changed": False,
                "message": (
                    "Vor echter Ausführung muss ein gültiges "
                    "Pre-Update-Backup gebunden sein."
                ),
            },
            {
                "order": 2,
                "id": "save_revision",
                "label": "Rollback-Commit speichern",
                "status": "simulated",
                "changed": False,
                "message": (
                    "Rollback-Ziel: {} / {}".format(
                        current_branch or "detached",
                        current_revision[:8],
                    )
                ),
            },
            {
                "order": 3,
                "id": "service_stop",
                "label": "ComfyUI-Dienst stoppen",
                "status": "simulated",
                "changed": False,
                "command": commands["service_stop"],
            },
            {
                "order": 4,
                "id": "stable_checkout",
                "label": (
                    "Auf Stable {} wechseln".format(
                        stable_version
                    )
                ),
                "status": "simulated",
                "changed": False,
                "command": commands["stable_checkout"],
            },
            {
                "order": 5,
                "id": "dependencies",
                "label": "ComfyUI-Abhängigkeiten abgleichen",
                "status": "simulated",
                "changed": False,
                "message": (
                    "PyTorch/CUDA bleibt unverändert."
                ),
                "command": commands["dependencies"],
            },
            {
                "order": 6,
                "id": "sanity_check",
                "label": "Python-/CUDA-Umgebung prüfen",
                "status": "simulated",
                "changed": False,
                "command": commands["sanity_check"],
            },
            {
                "order": 7,
                "id": "service_start",
                "label": "ComfyUI-Dienst starten",
                "status": "simulated",
                "changed": False,
                "command": commands["service_start"],
            },
            {
                "order": 8,
                "id": "verify",
                "label": "Stable-Commit und WebUI prüfen",
                "status": "simulated",
                "changed": False,
                "message": (
                    "Erwarteter Stable-Commit: {}".format(
                        stable_revision[:8]
                    )
                ),
            },
            {
                "order": 9,
                "id": "rollback",
                "label": "Fehler-Rollback",
                "status": "simulated",
                "changed": False,
                "conditional": True,
                "message": (
                    "Bei Fehler Rückkehr auf {}.".format(
                        current_revision[:8]
                    )
                ),
                "commands": [
                    commands["rollback_checkout"],
                    commands["rollback_dependencies"],
                    commands["rollback_start"],
                ],
            },
        ]

        return {
            "supported": True,
            "ok": True,
            "simulate": True,
            "mode": "simulation",
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "current_revision": current_revision,
            "current_branch": current_branch,
            "stable_version": stable_version,
            "stable_revision": stable_revision,
            "message": (
                "ComfyUI Stable-Wechsel erfolgreich simuliert."
            ),
            "torch_policy": {
                "change_torch": False,
                "reason": (
                    "Vorhandener CUDA/PyTorch-Stack ist "
                    "funktionsfähig und wird beim Stable-Wechsel "
                    "nicht verändert."
                ),
            },
            "commands": commands,
            "steps": steps,
        }


    def update_execute(self, session=None):
        """
        Führt ein ComfyUI-Update über Git und die vorhandene venv aus.

        Ablauf:
        - sauberes Git-Repository prüfen
        - Fast-Forward Git-Update
        - vorhandenen PyTorch/CUDA-Stack beibehalten und prüfen
        - ComfyUI requirements installieren
        - Python/CUDA/comfy-kitchen vor dem Restart prüfen
        - Dienst neu starten
        - stabilen Dienst und WebUI verifizieren

        Modelle und custom_nodes werden nicht verändert.
        """

        session = session if isinstance(session, dict) else {}
        simulate = bool(session.get("simulate", True))

        repo = host_literal('comfyui', "/opt/comfyui/ComfyUI")
        python = repo + "/venv/bin/python"
        requirements = repo + "/requirements.txt"

        plan = self.update_plan()

        stable_revision = str(
            plan.get("stable_revision") or ""
        ).strip()

        stable_version = str(
            plan.get("stable_version") or ""
        ).strip()

        steps = []

        def add_step(
            order,
            step_id,
            label,
            status,
            changed=False,
            message="",
            command="",
            output="",
            returncode=None,
        ):
            steps.append({
                "order": order,
                "id": step_id,
                "label": label,
                "status": status,
                "changed": bool(changed),
                "message": message,
                "command": command,
                "output": output,
                "returncode": returncode,
            })

        def combined_output(result):
            return (
                (result.get("stdout") or "")
                + "\n"
                + (result.get("stderr") or "")
            ).strip()

        def failure(message):
            return {
                "supported": True,
                "ok": False,
                "mode": "simulation" if simulate else "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": message,
                "steps": steps,
            }

        if not plan.get("update_available"):
            return {
                "supported": True,
                "ok": True,
                "mode": "simulation" if simulate else "execute",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "update_available": False,
                "state": plan.get("state"),
                "message": "Kein ComfyUI-Update erforderlich.",
                "steps": [],
            }

        if not stable_revision:
            return {
                "supported": True,
                "ok": False,
                "mode": "simulation" if simulate else "execute",
                "blocked": True,
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "message": (
                    "Kein gültiger ComfyUI Stable-Commit "
                    "für das Update vorhanden."
                ),
                "steps": [],
            }

        guard = plan.get("update_guard") or {}

        if guard.get("blocked"):
            add_step(
                1,
                "git_precheck",
                "ComfyUI Git-Repository prüfen",
                "blocked",
                False,
                guard.get("message") or (
                    "ComfyUI-Update ist blockiert."
                ),
                "",
                "\n".join(guard.get("details") or []),
                1,
            )

            result = failure(
                guard.get("message") or (
                    "ComfyUI-Update ist blockiert."
                )
            )
            result["blocked"] = True
            result["warnings"] = plan.get("warnings") or []
            return result

        precheck_cmd = (
            host_literal('comfyui', "sudo -n -u comfyui "
            "git -C /opt/comfyui/ComfyUI status --porcelain")
        )

        git_cmd = (
            host_literal('comfyui', "sudo -n -u comfyui "
            "git -C /opt/comfyui/ComfyUI merge --ff-only ")
            + repr(stable_revision)
        )

        # Der vorhandene PyTorch/CUDA-Stack wird bei normalen
        # ComfyUI-Updates bewusst nicht verändert. requirements.txt
        # darf bereits erfüllte ungepinnte Torch-Pakete weiterverwenden.
        torch_cmd = (
            host_literal('comfyui', "sudo -n -u comfyui ")
            + python
            + " -c "
            + repr(
                "import torch; "
                "print('torch=' + str(torch.__version__)); "
                "print('cuda=' + str(torch.version.cuda)); "
                "print('cuda_available=' + str(torch.cuda.is_available())); "
                "assert torch.cuda.is_available(), 'CUDA ist nicht verfügbar'"
            )
        )

        pip_cmd = (
            host_literal('comfyui', "sudo -n -u comfyui ")
            + python
            + " -m pip install -r "
            + requirements
        )

        sanity_code = (
            "import torch; "
            "from importlib.metadata import version; "
            "import comfy_kitchen; "
            "from comfy_kitchen.backends.eager import na; "
            "assert torch.cuda.is_available(), "
            "'CUDA ist für PyTorch nicht verfügbar'; "
            "print('torch=' + str(torch.__version__)); "
            "print('cuda=' + str(torch.version.cuda)); "
            "print('gpu=' + str(torch.cuda.get_device_name(0))); "
            "print('comfy_kitchen=' + version('comfy-kitchen')); "
            "print('comfy_kitchen_eager_na=ok')"
        )

        sanity_cmd = (
            host_literal('comfyui', "sudo -n -u comfyui ")
            + python
            + " -c "
            + repr(sanity_code)
        )

        restart_cmd = (
            "sudo -n systemctl restart comfyui.service"
        )

        precheck_r = sh(precheck_cmd, timeout=30)
        precheck_output = combined_output(precheck_r)

        precheck_ok = bool(
            precheck_r.get("ok")
            and not precheck_output.strip()
        )

        add_step(
            1,
            "git_precheck",
            "ComfyUI Git-Repository prüfen",
            "executed" if precheck_ok else "failed",
            False,
            (
                "ComfyUI Git-Repository ist sauber."
                if precheck_ok
                else (
                    "ComfyUI Git-Repository enthält lokale "
                    "Änderungen oder konnte nicht geprüft werden."
                )
            ),
            precheck_cmd,
            precheck_output,
            precheck_r.get("returncode"),
        )

        if not precheck_ok:
            return failure(
                "ComfyUI-Vorprüfung fehlgeschlagen."
            )

        if simulate:
            simulated_steps = [
                (
                    2,
                    "git_update",
                    "ComfyUI Repository aktualisieren",
                    (
                        "Simulation: ComfyUI {} würde auf "
                        "Stable {} ({}) aktualisiert."
                    ).format(
                        plan.get("current_version") or "unbekannt",
                        stable_version or "unbekannt",
                        stable_revision[:8] or "unbekannt",
                    ),
                    git_cmd,
                ),
                (
                    3,
                    "torch_dependencies",
                    "PyTorch/CUDA-Stack beibehalten",
                    (
                        "Simulation: vorhandener PyTorch/CUDA-Stack "
                        "würde unverändert weiterverwendet und geprüft."
                    ),
                    torch_cmd,
                ),
                (
                    4,
                    "python_dependencies",
                    "Python-Abhängigkeiten aktualisieren",
                    (
                        "Simulation: requirements.txt würde in der "
                        "ComfyUI-venv installiert."
                    ),
                    pip_cmd,
                ),
                (
                    5,
                    "python_sanity_check",
                    "Python-/CUDA-Umgebung prüfen",
                    (
                        "Simulation: PyTorch, CUDA und comfy-kitchen "
                        "würden vor dem Dienststart geprüft."
                    ),
                    sanity_cmd,
                ),
                (
                    6,
                    "service_restart",
                    "ComfyUI-Dienst neu starten",
                    "Simulation: comfyui.service würde neu gestartet.",
                    restart_cmd,
                ),
                (
                    7,
                    "service_verify",
                    "ComfyUI-Dienst und WebUI prüfen",
                    (
                        "Simulation: Git-Stand, Dienststabilität "
                        "und WebUI würden geprüft."
                    ),
                    "",
                ),
            ]

            for order, step_id, label, message, command in simulated_steps:
                add_step(
                    order,
                    step_id,
                    label,
                    "simulated",
                    False,
                    message,
                    command,
                    "",
                    0,
                )

            return {
                "supported": True,
                "ok": True,
                "simulate": True,
                "mode": "simulation",
                "app_id": self.app_id,
                "label": self.label,
                "kind": self.kind,
                "current_version": plan.get("current_version"),
                "latest_version": plan.get("latest_version"),
                "message": "ComfyUI-Update erfolgreich simuliert.",
                "steps": steps,
            }

        # ----------------------------------------------------
        # Git
        # ----------------------------------------------------

        git_r = sh(git_cmd, timeout=600)
        git_output = combined_output(git_r)
        git_ok = bool(git_r.get("ok"))

        add_step(
            2,
            "git_update",
            "ComfyUI Repository aktualisieren",
            "executed" if git_ok else "failed",
            git_ok,
            (
                "ComfyUI Repository wurde aktualisiert."
                if git_ok
                else "ComfyUI Git-Update ist fehlgeschlagen."
            ),
            git_cmd,
            git_output,
            git_r.get("returncode"),
        )

        if not git_ok:
            return failure(
                "ComfyUI Git-Update fehlgeschlagen."
            )

        # ----------------------------------------------------
        # PyTorch / CUDA
        # ----------------------------------------------------

        torch_r = sh(torch_cmd, timeout=1800)
        torch_output = combined_output(torch_r)
        torch_ok = bool(torch_r.get("ok"))

        add_step(
            3,
            "torch_dependencies",
            "PyTorch/CUDA-Stack beibehalten",
            "executed" if torch_ok else "failed",
            True,
            (
                "Vorhandener PyTorch/CUDA-Stack wurde geprüft und beibehalten."
                if torch_ok
                else (
                    "PyTorch/CUDA-Stack konnte nicht "
                    "aktualisiert werden."
                )
            ),
            torch_cmd,
            torch_output,
            torch_r.get("returncode"),
        )

        if not torch_ok:
            return failure(
                "ComfyUI wurde per Git aktualisiert, aber die "
                "PyTorch/CUDA-Stack konnte nicht erfolgreich geprüft werden."
            )

        # ----------------------------------------------------
        # restliche Requirements
        # ----------------------------------------------------

        pip_r = sh(pip_cmd, timeout=1800)
        pip_output = combined_output(pip_r)
        pip_ok = bool(pip_r.get("ok"))

        add_step(
            4,
            "python_dependencies",
            "Python-Abhängigkeiten aktualisieren",
            "executed" if pip_ok else "failed",
            True,
            (
                "Python-Abhängigkeiten wurden aktualisiert."
                if pip_ok
                else (
                    "Aktualisierung der Python-Abhängigkeiten "
                    "ist fehlgeschlagen."
                )
            ),
            pip_cmd,
            pip_output,
            pip_r.get("returncode"),
        )

        if not pip_ok:
            return failure(
                "ComfyUI und PyTorch wurden aktualisiert, aber die "
                "Python-Abhängigkeiten konnten nicht vollständig "
                "aktualisiert werden."
            )

        # ----------------------------------------------------
        # Sanity-Check VOR Service-Restart
        # ----------------------------------------------------

        sanity_r = sh(sanity_cmd, timeout=120)
        sanity_output = combined_output(sanity_r)
        sanity_ok = bool(sanity_r.get("ok"))

        add_step(
            5,
            "python_sanity_check",
            "Python-/CUDA-Umgebung prüfen",
            "executed" if sanity_ok else "failed",
            False,
            (
                "PyTorch, CUDA und comfy-kitchen sind funktionsfähig."
                if sanity_ok
                else (
                    "Python-/CUDA-Prüfung ist fehlgeschlagen. "
                    "ComfyUI wird nicht neu gestartet."
                )
            ),
            sanity_cmd,
            sanity_output,
            sanity_r.get("returncode"),
        )

        if not sanity_ok:
            return failure(
                "ComfyUI-Abhängigkeiten wurden verändert, aber der "
                "Python-/CUDA-Sanity-Check ist fehlgeschlagen. "
                "Der Dienst wurde nicht neu gestartet."
            )

        # ----------------------------------------------------
        # Service
        # ----------------------------------------------------

        restart_r = sh(restart_cmd, timeout=120)
        restart_output = combined_output(restart_r)
        restart_ok = bool(restart_r.get("ok"))

        add_step(
            6,
            "service_restart",
            "ComfyUI-Dienst neu starten",
            "executed" if restart_ok else "failed",
            restart_ok,
            (
                "ComfyUI-Dienst wurde neu gestartet."
                if restart_ok
                else "ComfyUI-Dienst konnte nicht neu gestartet werden."
            ),
            restart_cmd,
            restart_output,
            restart_r.get("returncode"),
        )

        if not restart_ok:
            return failure(
                "ComfyUI wurde aktualisiert, aber der Dienst "
                "konnte nicht neu gestartet werden."
            )

        # ----------------------------------------------------
        # Stabilitätsprüfung
        # ----------------------------------------------------

        verify = self.update_verify()

        add_step(
            7,
            "service_verify",
            "ComfyUI-Dienst und WebUI prüfen",
            "executed" if verify.get("ok") else "failed",
            False,
            verify.get("message") or "",
            "",
            "",
            0 if verify.get("ok") else 1,
        )

        return {
            "supported": True,
            "ok": bool(verify.get("ok")),
            "mode": "execute",
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "message": (
                "ComfyUI wurde aktualisiert und erfolgreich geprüft."
                if verify.get("ok")
                else (
                    "ComfyUI wurde aktualisiert, aber die "
                    "Verifikation ist fehlgeschlagen."
                )
            ),
            "steps": steps,
            "verify": verify,
        }

    def update_verify(self):
        """
        Prüft Git-Stand, Dienststabilität und WebUI nach dem Update.

        Der Dienst wird über mehrere Versuche beobachtet. Dadurch wird
        insbesondere eine systemd-Restart-Schleife erkannt, bei der
        systemctl is-active kurzzeitig "active" liefern kann.
        """

        check = self.update_check()

        update_available = check.get("update_available")

        details = check.get("details") or {}

        current_revision = str(
            details.get("local_revision") or ""
        ).strip()

        stable_revision = str(
            check.get("stable_revision") or ""
        ).strip()

        version_ok = bool(
            current_revision
            and stable_revision
            and current_revision == stable_revision
        )

        restart_r = sh(
            "systemctl show comfyui.service "
            "-p NRestarts --value 2>/dev/null || true",
            timeout=10,
        )

        try:
            restart_start = int(
                (restart_r.get("stdout") or "0").strip() or 0
            )
        except Exception:
            restart_start = 0

        attempts = []

        # Etwa 20 Sekunden Stabilitätsfenster.
        for attempt in range(1, 7):
            service = self._service_status()
            web = self._web_check()

            restart_r = sh(
                "systemctl show comfyui.service "
                "-p NRestarts --value 2>/dev/null || true",
                timeout=10,
            )

            try:
                restart_count = int(
                    (restart_r.get("stdout") or "0").strip() or 0
                )
            except Exception:
                restart_count = restart_start

            service_ok = (
                str(service.get("active") or "").strip()
                == "active"
            )

            web_ok = bool(web.get("ok"))

            attempts.append({
                "attempt": attempt,
                "service_active": service.get("active"),
                "service_ok": service_ok,
                "web_http": web.get("http_code"),
                "web_ok": web_ok,
                "restart_count": restart_count,
            })

            if attempt < 6:
                time.sleep(4)

        restart_end = (
            attempts[-1].get("restart_count")
            if attempts
            else restart_start
        )

        restart_stable = restart_end == restart_start

        service_stable = bool(
            attempts
            and all(
                item.get("service_ok")
                for item in attempts[-3:]
            )
        )

        web_stable = bool(
            attempts
            and all(
                item.get("web_ok")
                for item in attempts[-3:]
            )
        )

        ok = bool(
            version_ok
            and service_stable
            and web_stable
            and restart_stable
        )

        return {
            "supported": True,
            "ok": ok,
            "app_id": self.app_id,
            "label": self.label,
            "kind": self.kind,
            "message": (
                "ComfyUI Git-Stand, Dienst und WebUI sind stabil."
                if ok
                else "ComfyUI-Verifikation meldet einen instabilen Zustand."
            ),
            "current_version": check.get("current_version"),
            "candidate_version": check.get("latest_version"),
            "current_revision": current_revision,
            "stable_revision": stable_revision,
            "update_available": update_available,
            "version_ok": version_ok,
            "service_ok": service_stable,
            "web_ok": web_stable,
            "restart_stable": restart_stable,
            "restart_start": restart_start,
            "restart_end": restart_end,
            "attempts": attempts,
        }


    def extra_backup(self, workdir):
        """
        Sichert den für ein ComfyUI-Update relevanten Zustand.

        Modelle, virtuelle Python-Umgebung und das vollständige
        Git-Repository werden bewusst nicht kopiert.
        """

        out = Path(workdir)
        out.mkdir(parents=True, exist_ok=True)

        repo = Path(host_literal('comfyui', "/opt/comfyui/ComfyUI"))

        files = []
        results = {}

        def save_command(name, command, timeout=30):
            r = sh(command, timeout=timeout)

            target = out / name

            content = (
                (r.get("stdout") or "")
                + (
                    "\nSTDERR:\n" + (r.get("stderr") or "")
                    if r.get("stderr")
                    else ""
                )
            )

            target.write_text(
                content,
                encoding="utf-8",
            )

            files.append(str(target))

            results[name] = {
                "ok": bool(r.get("ok")),
                "returncode": r.get("returncode"),
            }

        # Git-Zustand vor dem Update.
        save_command(
            "git-head.txt",
            host_literal('comfyui', "sudo -n -u comfyui "
            "git -C /opt/comfyui/ComfyUI rev-parse HEAD"),
        )

        save_command(
            "git-branch.txt",
            host_literal('comfyui', "sudo -n -u comfyui "
            "git -C /opt/comfyui/ComfyUI status -sb"),
        )

        save_command(
            "git-status.txt",
            host_literal('comfyui', "sudo -n -u comfyui "
            "git -C /opt/comfyui/ComfyUI status --porcelain"),
        )

        save_command(
            "git-remotes.txt",
            host_literal('comfyui', "sudo -n -u comfyui "
            "git -C /opt/comfyui/ComfyUI remote -v"),
        )

        # Python-Zustand.
        save_command(
            "python-version.txt",
            host_literal('comfyui', "sudo -n -u comfyui "
            "/opt/comfyui/ComfyUI/venv/bin/python --version"),
        )

        save_command(
            "pip-freeze.txt",
            host_literal('comfyui', "sudo -n -u comfyui "
            "/opt/comfyui/ComfyUI/venv/bin/python "
            "-m pip freeze"),
            timeout=60,
        )

        # systemd-Service sichern.
        save_command(
            "comfyui.service.txt",
            "systemctl cat comfyui.service",
        )

        # Relevante Projektdateien kopieren.
        project_files = (
            "requirements.txt",
            "pyproject.toml",
            "requirements_versions.txt",
            "uv.lock",
        )

        for name in project_files:
            src = repo / name

            if not src.is_file():
                continue

            target = out / name
            target.write_bytes(src.read_bytes())
            files.append(str(target))

        return {
            "ok": all(
                item.get("ok")
                for item in results.values()
            ),
            "message": (
                "ComfyUI Update-Zustand gesichert."
            ),
            "repo": str(repo),
            "files": files,
            "commands": results,
        }


    def info(self):
        return {"python": sh('python3 --version 2>&1', timeout=5)['stdout'], "nvidia": sh('nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true', timeout=8)['stdout']}

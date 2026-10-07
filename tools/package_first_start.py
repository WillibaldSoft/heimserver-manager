#!/usr/bin/env python3
"""Initialize only missing settings and credentials, without importing the app."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server_settings as cfg
from authentication import Accounts

def initialize():
    fresh=not cfg.CONFIG.exists() and not (cfg.CONFIG_DIR/"authentication.json").exists()
    if not cfg.CONFIG.exists():
        values={
            'download_root':'/srv/server-manager/downloads','fotolabor_root':'/srv/fotolabor',
            'vm_root':'/srv/vm','iso_roots':['/srv/iso'],'media_roots':['/srv/vm','/srv/iso'],
            'kvm_ssh_host':'localhost','kvm_ssh_user':'admin','recover_url':'',
            'system_backup_root':'/srv/backups','backup_root':'/srv/backups/apps','restore_log_root':'/srv/backups/restore-runs','update_log_root':'/srv/backups/update-runs',
            'share_roots':['/srv','/mnt','/media'],'nextcloud_data':'/srv/nextcloud-data',
            'immich_root':'/opt/immich','paperless_data':'/srv/paperless/data','paperless_media':'/srv/paperless/media',
            'paperless_export':'/srv/paperless/export','paperless_consume':'/srv/paperless/consume','paperless_url':'http://127.0.0.1:8010',
            'comfyui_root':'/opt/comfyui','comfyui_user':'comfyui','oscam_root':'/opt/oscam','oscam_build':'/opt/oscam-build','oscam_user':'oscam',
            'backup_items':[],'storage_labels':{},
        }
        cfg.atomic(cfg.CONFIG,values)
    if fresh:
        from modules.first_start.config import initialize as initialize_selection
        initialize_selection()
    Accounts(cfg.CONFIG_DIR/'authentication.json')

if __name__=='__main__':initialize()

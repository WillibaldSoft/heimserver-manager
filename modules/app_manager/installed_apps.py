"""Dynamic managers for user-defined container apps (no executable profiles)."""
from pathlib import Path
from . import install_catalog as c
from .managers.open_webui import Manager as ContainerManager

def managers():
    result=[]
    profiles=c.recipes()
    for key,profile in profiles.items():
        if key=='pihole':
            from .install_runtime import pihole_existing
            from .managers.pihole_container import PiHoleManager,NativePiHoleManager
            detected=pihole_existing()
            if len(detected)==1:
                existing=detected[0]
                item=PiHoleManager() if existing['kind']=='docker' else NativePiHoleManager()
                if existing.get('container'):item.container=existing['container']
                item.web_url=existing['web_url']
                result.append(item);continue
        custom=key not in c.CATALOG
        fresh=(Path(profile['target'])/'.server-manager-install.json').is_file()
        if fresh and profile['kind']=='nextcloud_native':
            import server_settings as cfg
            from .managers.nextcloud import Manager
            current=cfg.load()
            for field in ('nextcloud_root','nextcloud_data','nextcloud_user'):cfg.ACTIVE[field]=current[field]
            item=Manager();item.web_url=profile['web_url']+'/status.php'
            item.paths={'nextcloud_app':current['nextcloud_root'],'nextcloud_data':current['nextcloud_data']}
            item.config_files={'config.php':current['nextcloud_root']+'/config/config.php','apache-nextcloud.conf':'/etc/apache2/sites-available/server-manager-nextcloud.conf'}
            result.append(item);continue
        if key=='nextcloud_docker':
            legacy=profiles.get('nextcloud',{})
            if not fresh and legacy.get('kind')=='nextcloud' and (Path(legacy['target'])/'.server-manager-install.json').is_file():continue
            from .nextcloud_variants import DockerNextcloud
            result.append(DockerNextcloud(profile));continue
        if not custom and not (fresh and profile['kind'] in ('container','nextcloud','paperless','immich')):continue
        if key=='pihole':
            from .managers.pihole_container import PiHoleManager
            item=PiHoleManager()
        else:item=ContainerManager()
        item.app_id=key;item.label=profile['label'];item.container=profile['container']
        if key=='nextcloud':
            from .nextcloud_variants import DockerNextcloud
            item=DockerNextcloud(profile)
        if key=='nextcloud':
            result.append(item);continue
        item.web_url=profile.get('web_url') or 'http://127.0.0.1:'+str(profile['port']);item.paths={'installation':profile['target']};item.config_files={}
        result.append(item)
    return result

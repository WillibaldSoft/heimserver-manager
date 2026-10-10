"""Conservative share constraints; the worker also runs with the user's Unix IDs."""
import ipaddress,json,os,pwd,re,grp
from pathlib import Path
from modules.shares import access,configuration,helpers

def identity(ctx,agent):
    con=ctx.db()
    try:row=con.execute('SELECT principal FROM client_bindings WHERE agent_id=?',(agent['id'],)).fetchone()
    finally:con.close()
    principal=json.loads(row['principal']) if row else {}
    if principal.get('kind')!='system':raise ValueError('Offline files require a linked Linux user, not the emergency administrator')
    try:user=pwd.getpwnam(principal['name'])
    except KeyError:raise ValueError('Linux user no longer exists')
    if user.pw_uid==0 or principal.get('uid')!=user.pw_uid:raise ValueError('Linux user identity changed or is not permitted')
    return user

def contains(base,path):
    return Path(base)==Path(path) or Path(base) in Path(path).parents

def permission(path,user,peer,smb_authenticated=False):
    """Intersect known shares and Linux permissions; never reinterpret advanced rules."""
    writable=True
    raw=configuration.smb_shares()
    if any(s.get('config',{}).get('path') and Path(path)!=Path(s['config']['path']) and contains(path,s['config']['path']) for s in raw):raise ValueError('Select the individual SMB share instead of its parent folder')
    matching=[s for s in raw if s.get('config',{}).get('path') and contains(s['config']['path'],path)]
    if matching:
        account=helpers.run(['pdbedit','-L','-v','-u',user.pw_name],timeout=10)
        flags=re.search(r'Account Flags:\s*\[([^]]+)\]',account.get('out',''))
        if not account.get('ok') or not flags or 'D' in flags[1]:raise ValueError('SMB account unavailable or disabled')
        effective=access.effective_configs();who=access.subject(user.pw_name)
        for share in matching:
            cfg=effective.get(share['name'].casefold())
            if not cfg:raise ValueError('SMB permissions cannot be checked')
            if any(cfg.get(k,'').strip() for k in ('force user','admin users','hosts allow','hosts deny','username map','valid users file','veto files','hide files','include','copy','preexec','root preexec')):
                raise ValueError('Unsupported SMB rules: '+', '.join(k for k in ('force user','admin users','hosts allow','hosts deny','username map','valid users file','veto files','hide files','include','copy','preexec','root preexec') if cfg.get(k,'').strip()))
            if any('%' in cfg.get(k,'') for k in ('path','valid users','invalid users','read list','write list','force user','force group')):raise ValueError('Dynamic SMB rules are unsupported')
            if access.yes(cfg.get('guest only','no')) or access.yes(cfg.get('hide unreadable','no')):raise ValueError('Advanced SMB identity or visibility rules cannot be inherited')
            modules=set(access.tokens(cfg.get('vfs objects','')))
            if modules-{'acl_xattr'}:raise ValueError('Unsupported Samba VFS modules')
            if access.yes(cfg.get('acl_xattr:ignore system acls','no')) or cfg.get('acl_xattr:security_acl_name','security.NTACL')!='security.NTACL':raise ValueError('Nonstandard Samba ACL storage is unsupported')
            group=cfg.get('force group','').strip().lstrip('+')
            if group:
                try:gid=grp.getgrnam(group).gr_gid
                except KeyError:raise ValueError('Forced Samba group does not exist')
                if gid not in os.getgrouplist(user.pw_name,user.pw_gid):raise ValueError('User is not a member of the forced Samba group')
            from .samba_acl import check_share
            try:check_share(share['name'],user)
            except ImportError as exc:raise ValueError('Samba Python bindings required (python3-samba)') from exc
            right=access.samba_right(cfg,who)
            if right['level'] not in ('read','write'):raise ValueError('SMB access denied or ambiguous')
            # Atomic local writes cannot yet preserve/inherit Windows NTACLs.
            # SMB sources are therefore read-only; never advertise unsafe writes.
            writable &= bool(smb_authenticated and right['level']=='write')
    exports=[x for x in configuration.nfs_exports() if contains(x['path'],path)]
    if exports:
        closest=max(len(Path(x['path']).parts) for x in exports)
        exports=[x for x in exports if len(Path(x['path']).parts)==closest]
        modes=[]
        for export in exports:
            for piece in export['clients'].split():
                match=re.fullmatch(r'([^()]+)\(([^()]+)\)',piece)
                if not match:raise ValueError('Advanced NFS export cannot be checked')
                try:net=ipaddress.ip_network(match[1],strict=False)
                except ValueError:raise ValueError('NFS hostnames or wildcards require a separate permission review')
                if ipaddress.ip_address(peer) not in net:continue
                opts=set(match[2].split(','))
                if opts-{'rw','ro','sync','async','no_subtree_check','subtree_check','root_squash','no_root_squash','sec=sys','secure','insecure'}:raise ValueError('Advanced NFS identity rules cannot be inherited')
                modes.append('rw' in opts)
        if not modes:raise ValueError('Client address is not authorized by the NFS export')
        writable &= all(modes)
    return bool(writable)

def creation_modes(path):
    file_mode=0o660;directory_mode=0o750
    shares=[s for s in configuration.smb_shares() if s.get('path') and contains(s['path'],path)]
    if shares:
        configs=access.effective_configs()
        for share in shares:
            cfg=configs.get(share['name'].casefold())
            if cfg is None:raise ValueError('SMB permissions unavailable')
            file_mode &= int(cfg.get('create mask','0744'),8)
            directory_mode &= int(cfg.get('directory mask','0755'),8)
    return file_mode,directory_mode

def uses_samba(path):
    return any(s.get('config',{}).get('path') and contains(s['config']['path'],path) for s in configuration.smb_shares())


def smb_target(path,user,peer):
    """Publish a route, never grant direct HTTPS write permissions."""
    if not permission(path,user,peer,smb_authenticated=True):return None
    matching=[s for s in configuration.smb_shares() if s.get('config',{}).get('path') and contains(s['config']['path'],path)]
    if not matching:return None
    configs=access.effective_configs();who=access.subject(user.pw_name)
    # Every overlapping share must agree. The actual SMB session enforces the
    # chosen share ACL and each file ACL again, using the supplied user password.
    if any(access.samba_right(configs[s['name'].casefold()],who)['level']!='write' for s in matching):return None
    share=max(matching,key=lambda s:len(Path(s['config']['path']).parts))
    rel=Path(path).relative_to(share['config']['path']).as_posix()
    return dict(share=share['name'],path='' if rel=='.' else rel,user=user.pw_name)

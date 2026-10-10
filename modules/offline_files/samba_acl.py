"""Read-only Samba ACL gate, using Samba's access_check and descriptor decoding.

A privileged broker reads protected NTACL attributes from already-open file
handles. The filesystem worker retains its unprivileged Unix identity.
Unresolved allow identities grant no rights; unresolved deny identities fail closed.
"""
import array,contextlib,errno,json,os,socket,threading

def check_descriptor(sd,user):
    from samba import security as checker,NTSTATUSError
    from samba.ndr import ndr_pack,ndr_unpack
    from samba.dcerpc import security
    # Nested NTACL descriptors are non-talloc views; access_check requires a
    # standalone descriptor. Binary round-trip preserves flags and ACEs exactly.
    sd=ndr_unpack(security.descriptor,ndr_pack(sd))
    from samba.samba3 import passdb
    from samba.samba3 import param
    lp=param.get_context();lp.load('/etc/samba/smb.conf')
    if lp.get('server role')!='standalone server' or lp.get('passdb backend')!='tdbsam':raise ValueError('Offline ACL checks require a standalone tdbsam server')
    db=passdb.PDB('tdbsam')
    groups=set(os.getgrouplist(user.pw_name,user.pw_gid))
    # Resolve every referenced identity, including deny ACEs. An incomplete
    # token must never accidentally omit a deny-group membership.
    members={'S-1-1-0','S-1-5-2','S-1-5-11'}
    for ace in (sd.dacl.aces if sd.dacl else []):
        # Inherit-only entries apply to descendants, not to this object.
        # Samba access_check skips them as well; do not resolve their placeholders.
        if ace.flags & security.SEC_ACE_FLAG_INHERIT_ONLY:continue
        sid=str(ace.trustee)
        if ace.type not in (0,1):raise ValueError('Unsupported Samba ACL entry')
        if sid in members:continue
        if sid=='S-1-3-0' or sid=='S-1-3-1':raise ValueError('Unresolved creator identity in Samba ACL')
        try:
            ident,kind=db.sid_to_id(ace.trustee)
        except Exception as exc:
            # An unresolved allow identity is never added to the token. Omitting
            # this potential grant can only restrict access. Deny identities
            # must still resolve, otherwise their membership could be missed.
            if ace.type==0:continue
            raise ValueError('Samba deny ACL identity cannot be resolved: '+sid) from exc
        if ace.type==1 and kind in (2,3) and ident not in groups and not sid.startswith('S-1-22-2-'):raise ValueError('Deny-group membership requires additional Samba alias resolution')
        if kind not in (1,2,3):
            if ace.type==0:continue
            raise ValueError('Unsupported Samba deny SID mapping: '+sid)
        if (kind in (1,3) and ident==user.pw_uid) or (kind in (2,3) and ident in groups):members.add(sid)
    token=security.token();token.num_sids=len(members);token.sids=[security.dom_sid(s) for s in sorted(members)]
    # Generic read includes data/list, attributes, EA and READ_CONTROL. This is
    # deliberately stricter than a data-only request.
    try:checker.access_check(sd,token,0x120089)
    except NTSTATUSError as exc:
        if exc.args and exc.args[0]==0xC0000022:raise PermissionError('Samba ACL denies read access') from exc
        raise ValueError('Samba ACL evaluation failed: '+str(exc)) from exc
    except Exception as exc:raise ValueError('Samba ACL evaluation failed: '+type(exc).__name__) from exc

def check_fd(fd,user):
    from samba.ndr import ndr_unpack
    from samba.dcerpc import xattr
    try:blob=os.getxattr(fd,'security.NTACL')
    except OSError as exc:
        if exc.errno==errno.ENODATA:return
        raise ValueError('Samba NTACL cannot be read') from exc
    try:
        acl=ndr_unpack(xattr.NTACL,blob)
        if acl.version not in (1,2,3,4):raise ValueError('Unknown NTACL version')
        sd=acl.info if acl.version==1 else acl.info.sd
    except Exception as exc:raise ValueError('Invalid Samba NTACL') from exc
    try:check_descriptor(sd,user)
    except (ValueError,PermissionError) as exc:
        raise PermissionError(str(exc)+' · '+os.readlink('/proc/self/fd/'+str(fd))) from exc

def check_share(name,user):
    from modules.shares import helpers
    from samba.dcerpc import security
    result=helpers.run(['sharesec',name,'--viewsddl'],timeout=10)
    if not result.get('ok'):raise ValueError('Samba share ACL cannot be read')
    text=result.get('out','').strip()
    # sharesec may prefix diagnostics, but never guess a missing descriptor.
    line=next((x.strip() for x in text.splitlines() if x.strip().startswith(('O:','D:','G:'))),None)
    if line is None:raise ValueError('Samba share ACL unavailable')
    try:sd=security.descriptor.from_sddl(line,security.dom_sid('S-1-0-0'))
    except Exception as exc:raise ValueError('Samba share ACL invalid') from exc
    check_descriptor(sd,user)

@contextlib.contextmanager
def broker(user):
    parent,child=socket.socketpair(socket.AF_UNIX,socket.SOCK_SEQPACKET)
    def serve():
        while True:
            fds=array.array('i')
            try:
                data,anc,flags,_=parent.recvmsg(16,socket.CMSG_SPACE(fds.itemsize))
                if not data:break
                for level,kind,value in anc:
                    if level==socket.SOL_SOCKET and kind==socket.SCM_RIGHTS:fds.frombytes(value[:len(value)-len(value)%fds.itemsize])
                if len(fds)!=1 or flags & socket.MSG_CTRUNC:raise ValueError('Invalid ACL request')
                check_fd(fds[0],user);answer={'ok':True}
            except Exception as exc:answer={'error':str(exc)}
            finally:
                for fd in fds:os.close(fd)
            try:parent.send(json.dumps(answer).encode())
            except OSError:break
    thread=threading.Thread(target=serve,daemon=True);thread.start()
    try:yield child.fileno()
    finally:
        child.close()
        with contextlib.suppress(OSError):parent.shutdown(socket.SHUT_RDWR)
        thread.join(timeout=2);parent.close()

def guard(fd):
    number=os.environ.get('HSM_OFFLINE_ACL_FD')
    if not number:return
    with socket.socket(fileno=os.dup(int(number))) as sock:
        sock.settimeout(15)
        sock.sendmsg([b'check'],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array('i',[fd]))])
        result=json.loads(sock.recv(8192))
    if not result.get('ok'):raise PermissionError(result.get('error','Samba ACL check failed'))

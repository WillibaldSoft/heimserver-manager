"""Isolated Linux-PAM password/account check. Credentials only arrive on stdin."""
import ctypes as C
import json,sys,resource
class Message(C.Structure):_fields_=[('style',C.c_int),('text',C.c_char_p)]
class Response(C.Structure):_fields_=[('text',C.c_void_p),('code',C.c_int)]
Callback=C.CFUNCTYPE(C.c_int,C.c_int,C.POINTER(C.POINTER(Message)),C.POINTER(C.POINTER(Response)),C.c_void_p)
class Conversation(C.Structure):_fields_=[('callback',Callback),('data',C.c_void_p)]
def authenticate(username,password,*,_test_confdir=None):
    if not username or not password or '\0' in username+password or len(password)>256:return False
    libc=C.CDLL('libc.so.6');pam=C.CDLL('libpam.so.0')
    libc.calloc.argtypes=[C.c_size_t,C.c_size_t];libc.calloc.restype=C.c_void_p
    libc.strdup.argtypes=[C.c_char_p];libc.strdup.restype=C.c_void_p
    libc.free.argtypes=[C.c_void_p]
    @Callback
    def conversation(count,messages,result,data):
        if not 1<=count<=32:return 19
        memory=libc.calloc(count,C.sizeof(Response))
        if not memory:return 5
        responses=C.cast(memory,C.POINTER(Response))
        try:
            for i in range(count):
                style=messages[i].contents.style
                if style in (1,2):
                    responses[i].text=libc.strdup((password if style==1 else username).encode())
                    if not responses[i].text:raise MemoryError()
                elif style not in (3,4):raise ValueError()
            result[0]=responses;return 0
        except Exception:
            for i in range(count):
                if responses[i].text:libc.free(responses[i].text)
            libc.free(memory);return 19
    pam.pam_start.argtypes=[C.c_char_p,C.c_char_p,C.POINTER(Conversation),C.POINTER(C.c_void_p)]
    pam.pam_authenticate.argtypes=[C.c_void_p,C.c_int]
    pam.pam_acct_mgmt.argtypes=[C.c_void_p,C.c_int]
    pam.pam_end.argtypes=[C.c_void_p,C.c_int]
    handle=C.c_void_p();conv=Conversation(conversation,None)
    if _test_confdir is None:
        result=pam.pam_start(b'server-manager',username.encode(),C.byref(conv),C.byref(handle))
    else:
        pam.pam_start_confdir.argtypes=[C.c_char_p,C.c_char_p,C.POINTER(Conversation),C.c_char_p,C.POINTER(C.c_void_p)]
        result=pam.pam_start_confdir(b'server-manager',username.encode(),C.byref(conv),str(_test_confdir).encode(),C.byref(handle))
    if result:return False
    try:
        result=pam.pam_authenticate(handle,1)  # PAM_DISALLOW_NULL_AUTHTOK
        if result==0:result=pam.pam_acct_mgmt(handle,1)
        return result==0
    finally:pam.pam_end(handle,result)
if __name__=='__main__':
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    try:
        data=json.loads(sys.stdin.buffer.read(8193))
        ok=authenticate(data['username'],data['password'])
    except Exception:ok=False
    print('OK' if ok else 'DENIED')

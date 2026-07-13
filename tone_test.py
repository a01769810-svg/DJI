import socket,time,sys
def tab(p):
    t=[]
    for i in range(256):
        c=i
        for _ in range(8): c=(c>>1)^p if c&1 else c>>1
        t.append(c)
    return t
T8=tab(0x8c); T16=tab(0x8408)
def crc8(d,c=0x77):
    for b in d: c=T8[(b^c)&0xff]
    return c
def crc16(d,v=0x3692):
    for b in d: v=(v>>8)^T16[(b^v)&0xff]
    return v&0xffff
SESS=bytes.fromhex("4d6e")
HELLO=bytes.fromhex("30804d6e00000093687264006400c005140000640000019001c005140000640014006400c00514000064000101040102")
D=("192.168.2.1",9003)
INIT=["550d0433020e95e5400001981f","551204c7022899e54000b70101000c0094e0","552204ea02039ee540114a00000000000088d3c0000000000088d3c05f3b546af603","550e04660228aae54000510654fa","552504840207cde5400793012b230032303230656534642d366163612d343636662d000e2f","553304c2eee90200405134000402000032303230656534642d366163612d343636662d00000000000000000000000000006b21","55430474cec80000001837010200000000000000000000000000010000000000000000000000000000000000000000000000000000000000000000000000000000b506","553d041ecec8000040183c0d000400010500000000000000000102000000000000000000000000010100000000000000000000000000000000000033a4"]
DAT03=bytes.fromhex("0e468601049b06fa")
def wrap(n,L): return bytes([L&0xff,0x80])+SESS+((0x9600+n*0x20)&0xffff).to_bytes(2,'little')+bytes([5,n&0xff])+((0x100000+n*0x30)&0xffffffff).to_bytes(4,'little')+bytes([0,0,0,0,n&0xff,1,0,0])
def wf(n,fr): return wrap(n,20+len(fr))+fr
def sf(seq,r,p,th,y):
    V=(r&0x7ff)|((p&0x7ff)<<11)|((th&0x7ff)<<22)|((y&0x7ff)<<33)
    b=bytes([0x55,0x29,0x04,0xc9,0x02,0xa9])+(seq&0xffff).to_bytes(2,'little')+bytes([0,1,0x0a,1,0x0d,0])+V.to_bytes(6,'little')+bytes([0x40,0,2,0,0,6,0x55,1,4,0x56,8,0,0,0,0,0,0,0,0])
    return b+crc16(b).to_bytes(2,'little')
def f20(seq,st,ctr):
    dat=DAT03 if st==3 else bytes(8)
    b=bytes([0x55,0x1a,0x04,0xb1,0x02,0x03])+(seq&0xffff).to_bytes(2,'little')+bytes([0x40,0x03,0x20,st&0xff])+dat+(ctr&0xffffffff).to_bytes(4,'little')
    return b+crc16(b).to_bytes(2,'little')
def tf(seq):
    b=bytes([0x55,0x12,0x04,0xc7,0x02,0x03])+(seq&0xffff).to_bytes(2,'little')+bytes([0x40,0x03,0xda,0x05,0xff,0xff,0xff,0xff])
    return b+crc16(b).to_bytes(2,'little')
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(("0.0.0.0",0)); s.settimeout(0.005)
got=False
for _ in range(6):
    s.sendto(HELLO,D); t0=time.time()
    while time.time()-t0<0.2:
        try:
            d,a=s.recvfrom(2048)
            if a[0]==D[0] and d[:2].hex()=="0980": got=True
        except socket.timeout: pass
    if got: break
print("hello ->","ACK" if got else "SIN ack")
if not got: sys.exit()
for h in INIT:
    s.sendto(wf(0,bytes.fromhex(h)),D); time.sleep(0.03)
n=1; ctr=0x6a545000
def run(dur,st,r,p,th,y,fire=0,label=""):
    global n,ctr
    if label: print(label,flush=True)
    end=time.time()+dur; nc=0.0; nh=0.0; nf=0.0; fired=0
    while time.time()<end:
        now=time.time()
        if now>=nc: s.sendto(wf(n,sf(n,r,p,th,y)),D); n+=1; nc=now+0.05
        if now>=nf: s.sendto(wf(n,f20(n,st,ctr)),D); n+=1; ctr+=1; nf=now+1.0
        if fired<fire: s.sendto(wf(n,tf(n)),D); n+=1; fired+=1; print("   >>> DESPEGUE enviado",fired,flush=True)
        if now>=nh: s.sendto(HELLO,D); nh=now+0.5
        try: s.recvfrom(2048)
        except socket.timeout: pass
        except BlockingIOError: pass
print("== TONE TEST: dron ASEGURADO, escucha el tono ==",flush=True)
run(2.0,2,1024,1024,1024,1024,label="1) autoridad-02 + neutro")
run(2.0,3,1024,1024,1024,1024,label="2) autoridad-03 + neutro")
run(1.0,3,1024,1024,1024,1024,fire=3,label="3) >>> DESPEGUE - ESCUCHA EL TONO <<<")
run(3.0,3,1024,1024,364,1024,label="4) throttle ABAJO (por si giro)")
s.close()
print("FIN tone test.",flush=True)

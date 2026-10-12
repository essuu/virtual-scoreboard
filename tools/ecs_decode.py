"""Usage: python ecs_decode.py CAPTURE.sr [...]

ECS cricket scoreboard decoder (from sigrok .sr logic capture, D0 = TX2 TXD).
Frame: Manchester ~940 bit/s, sync = 4 half-bits high, 32 data bits.
Invert bits; 4 groups of 8: [3-bit group index 3..0][4-bit BCD digit][1 spare bit].
Group 3 digit = field ID; groups 2,1,0 = hundreds, tens, units (0xF = blank)."""
import numpy as np, os, sys, zipfile, re
from collections import Counter
FIELDS={0:'Umpire light',1:'LH bat no.',2:'RH bat no.',3:'LH bat runs',4:'RH bat runs',5:'Total',6:'Wickets',7:'Overs',8:'Extras',9:'Last batter',10:'Total at last wkt',11:'1st inns total',12:'Runs required',13:'Overs remaining',14:'Bowler no.?/DLS par'}
def load(path):
    z=zipfile.ZipFile(path); meta=z.read('metadata').decode()
    sr=float(re.search(r'samplerate=([\d.]+) (\w*)Hz',meta).group(1))*{'':1,'k':1e3,'M':1e6}[re.search(r'samplerate=[\d.]+ (\w*)Hz',meta).group(1)]
    names=sorted([n for n in z.namelist() if n.startswith('logic-1-')],key=lambda n:int(n.split('-')[-1]))
    return np.frombuffer(b''.join(z.read(n) for n in names),dtype=np.uint8), sr
def frames(d,sr):
    b=(d&1).astype(np.int8); e=np.nonzero(np.diff(b))[0]+1; T=531e-6*sr
    bursts=[];cur=[];start=None
    for i in range(len(e)-1):
        n=int(round((e[i+1]-e[i])/T))
        if n>20:
            if cur: bursts.append((start,''.join(cur))); cur=[]
            continue
        if not cur: start=e[i]/sr
        cur.append(str(b[e[i]])*n)
    if cur: bursts.append((start,''.join(cur)))
    for t,s in bursts:
        fs=[]
        for p in s.split('1111')[1:]:
            h=p[1:65]
            if len(h)<64: continue
            bits=''.join('0' if h[i:i+2]=='10' else '1' if h[i:i+2]=='01' else 'X' for i in range(0,64,2))
            if 'X' not in bits: fs.append(bits)
        if fs:
            bits,n=Counter(fs).most_common(1)[0]
            yield t,bits,n,len(fs)
for path in sys.argv[1:]:
    d,sr=load(path); print('==',os.path.basename(path))
    for t,bits,n,tot in frames(d,sr):
        g=[bits[i:i+8] for i in range(0,32,8)]
        idx=[int(x[:3],2) for x in g]; dig=[int(x[3:7],2) for x in g]; spare=[x[7] for x in g]
        val=''.join(' ' if x==15 else str(x) for x in dig[1:])
        ok='ok' if idx==[3,2,1,0] else 'IDX?'
        print('t=%6.2fs field=%2d %-18s [%s] (%d/%d frames) %s'%(t,dig[0],FIELDS.get(dig[0],'?'),val,n,tot,ok))

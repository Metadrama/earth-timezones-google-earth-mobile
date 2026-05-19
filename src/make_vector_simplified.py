#!/usr/bin/env python3
from pathlib import Path
import struct, html, math, zipfile

BASE=Path('/tmp/timezones_kml')
ZIP=BASE/'ne_time_zones.zip'
WORK=BASE/'ne'
WORK.mkdir(exist_ok=True)
with zipfile.ZipFile(ZIP) as z:
    z.extractall(WORK)
shp=WORK/'ne_10m_time_zones.shp'
dbf=WORK/'ne_10m_time_zones.dbf'

def read_dbf(path):
    data=Path(path).read_bytes()
    nrec=struct.unpack('<I', data[4:8])[0]
    hlen=struct.unpack('<H', data[8:10])[0]
    rlen=struct.unpack('<H', data[10:12])[0]
    fields=[]; off=32
    while data[off] != 0x0D:
        raw=data[off:off+32]
        name=raw[0:11].split(b'\0',1)[0].decode('ascii','ignore')
        typ=chr(raw[11]); size=raw[16]; dec=raw[17]
        fields.append((name,typ,size,dec))
        off+=32
    recs=[]; pos=hlen
    for _ in range(nrec):
        rec=data[pos:pos+rlen]; pos+=rlen
        if not rec or rec[0:1]==b'*': continue
        cur=1; d={}
        for name,typ,size,dec in fields:
            val=rec[cur:cur+size].decode('latin1','ignore').strip(); cur+=size
            d[name]=val
        recs.append(d)
    return fields,recs

def read_shp(path):
    data=Path(path).read_bytes(); pos=100; shapes=[]
    while pos < len(data):
        recno, clen = struct.unpack('>2i', data[pos:pos+8]); pos+=8
        content=data[pos:pos+clen*2]; pos+=clen*2
        stype=struct.unpack('<i', content[:4])[0]
        if stype not in (5,15,25):
            shapes.append([]); continue
        # Polygon: type, bbox 32, numParts, numPoints, parts[], points[]
        n_parts,n_pts=struct.unpack('<2i', content[36:44])
        parts=list(struct.unpack('<%di'%n_parts, content[44:44+4*n_parts]))
        pts_off=44+4*n_parts
        pts=[struct.unpack('<2d', content[pts_off+i*16:pts_off+i*16+16]) for i in range(n_pts)]
        rings=[]
        for i,start in enumerate(parts):
            end=parts[i+1] if i+1<len(parts) else n_pts
            rings.append(pts[start:end])
        shapes.append(rings)
    return shapes

def rdp(points, eps):
    if len(points) <= 3: return points
    # keep closed rings closed, simplify open part then close
    closed = points[0] == points[-1]
    pts = points[:-1] if closed else points
    if len(pts) <= 3: return points
    def perp(p,a,b):
        ax,ay=a; bx,by=b; px,py=p
        dx=bx-ax; dy=by-ay
        if dx==0 and dy==0: return math.hypot(px-ax, py-ay)
        t=max(0,min(1,((px-ax)*dx+(py-ay)*dy)/(dx*dx+dy*dy)))
        x=ax+t*dx; y=ay+t*dy
        return math.hypot(px-x, py-y)
    def rec(seq):
        if len(seq)<=2: return seq
        a,b=seq[0],seq[-1]
        maxd=-1; idx=-1
        for i,p in enumerate(seq[1:-1],1):
            d=perp(p,a,b)
            if d>maxd: maxd=d; idx=i
        if maxd>eps:
            left=rec(seq[:idx+1]); right=rec(seq[idx:])
            return left[:-1]+right
        return [a,b]
    out=rec(pts)
    if closed and out[0] != out[-1]: out.append(out[0])
    return out

def fmt_coords(ring):
    return ' '.join(f'{x:.3f},{y:.3f},0' for x,y in ring)

fields,recs=read_dbf(dbf)
shapes=read_shp(shp)
print('fields', [f[0] for f in fields])
print('records', len(recs), 'shapes', len(shapes))

def get_name(rec):
    for k in ['zone','ZONE','name','NAME','time_zone','TIME_ZONE','utc_format','UTC_FORMAT']:
        if k in rec and rec[k]: return rec[k]
    vals=[v for v in rec.values() if v]
    return vals[0] if vals else 'timezone'

def make(eps, minpts, outname, fill=False):
    styles='''
    <Style id="tzLine"><LineStyle><color>ff00ffff</color><width>1.4</width></LineStyle><PolyStyle><color>00000000</color><fill>0</fill><outline>1</outline></PolyStyle></Style>
    <Style id="tzFill"><LineStyle><color>aa00ffff</color><width>1.0</width></LineStyle><PolyStyle><color>2200ffff</color><fill>1</fill><outline>1</outline></PolyStyle></Style>
    '''
    pms=[]; totalpts=0; keptrings=0
    for rec,rings in zip(recs,shapes):
        name=html.escape(get_name(rec))
        desc=html.escape(' | '.join(f'{k}: {v}' for k,v in rec.items() if v and k.lower() in ('zone','utc_format','time_zone','places','name','dst')))
        polys=[]
        for ring in rings:
            simp=rdp(ring, eps)
            if len(simp) < minpts: continue
            # skip tiny island artifacts after simplification
            xs=[p[0] for p in simp]; ys=[p[1] for p in simp]
            if (max(xs)-min(xs))*(max(ys)-min(ys)) < 0.02: continue
            totalpts += len(simp); keptrings += 1
            polys.append(f'''<Polygon><tessellate>1</tessellate><outerBoundaryIs><LinearRing><coordinates>{fmt_coords(simp)}</coordinates></LinearRing></outerBoundaryIs></Polygon>''')
        if polys:
            pms.append(f'''<Placemark><name>{name}</name><description>{desc}</description><styleUrl>{'#tzFill' if fill else '#tzLine'}</styleUrl><MultiGeometry>{''.join(polys)}</MultiGeometry></Placemark>''')
    kml=f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Earth timezones mobile-light ({outname})</name>{styles}{''.join(pms)}</Document></kml>'''
    out=BASE/outname
    out.write_text(kml)
    print(outname, 'bytes', out.stat().st_size, 'placemarks', len(pms), 'rings', keptrings, 'points', totalpts)

make(0.20, 4, 'earth_timezones_mobile_light.kml', fill=False)
make(0.50, 4, 'earth_timezones_ultra_light.kml', fill=False)
make(0.50, 4, 'earth_timezones_ultra_light_fill.kml', fill=True)
with zipfile.ZipFile(BASE/'earth_timezones_google_earth_mobile.zip','w',zipfile.ZIP_DEFLATED) as z:
    for n in ['earth_timezones_mobile_light.kml','earth_timezones_ultra_light.kml','earth_timezones_ultra_light_fill.kml']:
        z.write(BASE/n, n)
print('zip', (BASE/'earth_timezones_google_earth_mobile.zip').stat().st_size)
